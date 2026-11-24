from rest_framework import viewsets, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.views import APIView
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
from django.db.models import Q, Sum, Count, F, ProtectedError
from django.db.models.functions import TruncDate
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.permissions import IsAdminUser
from django.contrib.auth import authenticate, login as django_login, logout as django_logout
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny


import os
import requests
from urllib.parse import urlencode
from django.http import HttpResponseRedirect
from django.views.decorators.csrf import csrf_exempt

import csv
import io
import math
import uuid
from decimal import Decimal
from django.db import transaction, IntegrityError
import unicodedata


import re
from django.core.validators import validate_email
from django.core.exceptions import ValidationError


from .models import (
    Repuesto, Categoria, Subcategoria, Vehiculo, Pedido, Usuario, SolicitudEspecial,
    TarifaDespacho, DetallePedido, TransaccionPago,
)

from .serializers import (
    RepuestoSerializer,
    CategoriaSerializer,
    SubcategoriaSerializer,
    VehiculoSerializer,
    PedidoSerializer,
)
from .services.vin_service import MockBuscadorVehiculo

# --- Webpay Plus (ambiente de INTEGRACIÓN por defecto) ---
# En producción se definen por variables de entorno con las credenciales reales.
WEBPAY_HOST = os.environ.get('WEBPAY_HOST', 'https://webpay3gint.transbank.cl')
WEBPAY_API = '/rswebpaytransaction/api/webpay/v1.2/transactions'
WEBPAY_HEADERS = {
    'Tbk-Api-Key-Id': os.environ.get('WEBPAY_COMMERCE_CODE', '597055555532'),
    'Tbk-Api-Key-Secret': os.environ.get(
        'WEBPAY_API_KEY',
        '579B532A7440BB0C9079DED94D31EA1615BACEB56610332264630D42D0A36B1C',
    ),
    'Content-Type': 'application/json',
}
BACKEND_URL = os.environ.get('BACKEND_URL', 'http://localhost:8000')
FRONTEND_URL = os.environ.get('FRONTEND_URL', 'http://localhost:4200')




@api_view(['POST'])
@permission_classes([AllowAny])
def login_api_view(request):
    email = request.data.get('email')
    password = request.data.get('password')

    if not email or not password:
        return Response({"error": "Debe proporcionar correo y contraseña."}, status=status.HTTP_400_BAD_REQUEST)

    # Buscamos al usuario por su email (Django usa 'username' por defecto, pero mapeamos el email)
    from django.contrib.auth.models import User
    try:
        user_obj = User.objects.get(email=email)
        username = user_obj.username
    except User.DoesNotExist:
        return Response({"error": "Credenciales inválidas."}, status=status.HTTP_401_UNAUTHORIZED)

    user = authenticate(username=username, password=password)

    if user is not None:
        django_login(request, user)  # crea la sesión para que la API sepa quién eres

    if user is not None:
        # Si tiene first_name (ej: "Sebastian"), usamos solo el primer nombre; si no, usamos su username (ej: "admin")
        nombre_corto = user.first_name.split()[0] if user.first_name else user.username

        return Response({
            "mensaje": "Login exitoso",
            "is_staff": user.is_staff,
            "username": user.username,
            "nombre": nombre_corto,
            "email": user.email
        }, status=status.HTTP_200_OK)
    else:
        return Response({"error": "Contraseña incorrecta."}, status=status.HTTP_401_UNAUTHORIZED)

@api_view(['POST'])
@permission_classes([AllowAny])
def logout_api_view(request):
    django_logout(request)
    return Response({'mensaje': 'Sesión cerrada.'}, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([AllowAny])
def register_api_view(request):
    from django.contrib.auth.models import User
    from django.contrib.auth.hashers import make_password
    from .models import Usuario
    
    rut = _rut_valido(request.data.get('rut', ''))
    if not rut:
        return Response({"error": "El RUT no es válido."}, status=status.HTTP_400_BAD_REQUEST)
    nombre_completo = request.data.get('nombre_completo', '').strip()
    email = request.data.get('email', '').strip()
    password = request.data.get('password')
    telefono = request.data.get('telefono', '').strip()
    rol = request.data.get('rol', 'CLIENTE')

    if not email or not password or not nombre_completo or not rut:
        return Response(
            {"error": "Todos los campos obligatorios (RUT, nombre, correo y contraseña) deben estar completos."},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Validamos duplicados tanto en tu tabla Usuario como en la de Django
    if Usuario.objects.filter(email=email).exists() or User.objects.filter(email=email).exists():
        return Response(
            {"error": "Ya existe una cuenta registrada con este correo electrónico."},
            status=status.HTTP_400_BAD_REQUEST
        )

    if Usuario.objects.filter(rut=rut).exists():
        return Response(
            {"error": "Este RUT ya se encuentra registrado en el sistema."},
            status=status.HTTP_400_BAD_REQUEST
        )

    # 1. Guardamos en tu tabla personalizada Usuario (donde van el carrito, pedidos, etc.)
    nuevo_usuario = Usuario.objects.create(
        rut=rut,
        nombre_completo=nombre_completo,
        email=email,
        password_hash=make_password(password), # Encriptamos la clave por seguridad
        telefono=telefono,
        rol=rol
    )

    # 2. Creamos también el User nativo de Django respetando nombres compuestos
    first_name = request.data.get('first_name', '').strip()
    last_name = request.data.get('last_name', '').strip()

    if not first_name:
        partes_nombre = nombre_completo.split(' ', 1)
        first_name = partes_nombre[0]
        last_name = partes_nombre[1] if len(partes_nombre) > 1 else ''

    User.objects.create_user(
        username=email,
        email=email,
        password=password,
        first_name=first_name,
        last_name=last_name
    )

    return Response(
        {
            "mensaje": "Usuario registrado exitosamente.",
            "usuario_id": nuevo_usuario.id,
            "nombre": nuevo_usuario.nombre_completo,
            "email": nuevo_usuario.email,
            "rol": nuevo_usuario.rol
        },
        status=status.HTTP_201_CREATED
    )

class SoloAdminEscribeMixin:
    """Lectura pública; crear, editar y eliminar solo para administradores."""
    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            return []
        return [IsAdminUser()]


def clave_alfabetica(texto):
    """Clave de orden sin distinguir mayúsculas ni tildes ("Ácido" junto a "acido")."""
    texto = unicodedata.normalize('NFD', texto or '')
    return ''.join(c for c in texto if unicodedata.category(c) != 'Mn').casefold()


class OrdenAlfabeticoMixin:
    """Lista ordenada por nombre en Python: SQLite no ordena ignorando tildes."""
    def list(self, request, *args, **kwargs):
        objetos = sorted(self.filter_queryset(self.get_queryset()), key=lambda o: clave_alfabetica(o.nombre))
        return Response(self.get_serializer(objetos, many=True).data)


class CategoriaViewSet(OrdenAlfabeticoMixin, SoloAdminEscribeMixin, viewsets.ModelViewSet):
    queryset = Categoria.objects.all().order_by('id')
    serializer_class = CategoriaSerializer

    def destroy(self, request, *args, **kwargs):
        # Repuesto.categoria usa CASCADE: borrar la categoría borraría sus repuestos.
        categoria = self.get_object()
        if Repuesto.objects.filter(categoria=categoria).exists():
            return Response(
                {'error': 'No se puede eliminar: la categoría tiene repuestos asociados.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return super().destroy(request, *args, **kwargs)


class SubcategoriaViewSet(OrdenAlfabeticoMixin, SoloAdminEscribeMixin, viewsets.ModelViewSet):
    queryset = Subcategoria.objects.all().order_by('id')
    serializer_class = SubcategoriaSerializer

    def destroy(self, request, *args, **kwargs):
        subcategoria = self.get_object()
        if Repuesto.objects.filter(subcategoria=subcategoria).exists():
            return Response(
                {'error': 'No se puede eliminar: la subcategoría tiene repuestos asociados.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return super().destroy(request, *args, **kwargs)


class VehiculoViewSet(SoloAdminEscribeMixin, viewsets.ModelViewSet):
    queryset = Vehiculo.objects.all().order_by('marca', 'modelo', 'anio_inicio')
    serializer_class = VehiculoSerializer

class PaginacionOpcional(PageNumberPagination):
    """Pagina solo si se pide ?page=. Sin él la lista sigue siendo un arreglo (la tienda la usa así)."""
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100

    def paginate_queryset(self, queryset, request, view=None):
        if self.page_query_param not in request.query_params:
            return None
        return super().paginate_queryset(queryset, request, view)


STOCK_CRITICO = 5


class RepuestoViewSet(viewsets.ModelViewSet):
    queryset = Repuesto.objects.select_related('categoria', 'subcategoria').order_by('-id')
    serializer_class = RepuestoSerializer
    pagination_class = PaginacionOpcional

    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            return []
        return [IsAdminUser()]

    def get_queryset(self):
        qs = super().get_queryset()
        if self.action != 'list':
            return qs
        p = self.request.query_params
        q = p.get('q', '').strip()
        if q:
            qs = qs.filter(Q(nombre__icontains=q) | Q(sku__icontains=q) | Q(codigo_oem__icontains=q))
        if p.get('categoria', '').isdigit():
            qs = qs.filter(categoria_id=p['categoria'])
        if p.get('condicion'):
            qs = qs.filter(condicion=p['condicion'].upper())
        if p.get('stock_critico') in ('1', 'true'):
            qs = qs.filter(stock_disponible__lte=STOCK_CRITICO)
        return qs

    def destroy(self, request, *args, **kwargs):
        # DetallePedido protege los repuestos ya vendidos: se desactivan en vez de borrarse
        try:
            return super().destroy(request, *args, **kwargs)
        except ProtectedError:
            return Response(
                {'error': 'No se puede eliminar: el repuesto tiene pedidos asociados. Desactívalo para ocultarlo de la tienda.'},
                status=status.HTTP_400_BAD_REQUEST,
            )


class PedidoViewSet(viewsets.ModelViewSet):
    # Contiene datos personales (RUT, correo, dirección): solo administradores
    queryset = Pedido.objects.all()
    serializer_class = PedidoSerializer
    permission_classes = [IsAdminUser]


class BuscarVehiculoAPIView(APIView):
    """
    Endpoint para buscar vehículos por Patente o VIN utilizando el Patrón Adaptador.
    """
    def get(self, request):
        # Capturamos el parámetro 'q' de la URL (ej: /api/buscar-vehiculo/?q=ABCD12)
        identificador = request.query_params.get('q', '').strip()

        if not identificador:
            return Response(
                {"error": "Debe proporcionar una patente o VIN en el parámetro 'q'."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Patrón adaptador instanciado
        buscador = MockBuscadorVehiculo()
        resultado = buscador.buscar(identificador)

        if resultado:
            return Response(resultado, status=status.HTTP_200_OK)
        else:
            return Response(
                {"error": "Vehículo no encontrado en los registros."},
                status=status.HTTP_404_NOT_FOUND
            )


@api_view(['POST'])
@permission_classes([AllowAny])
def solicitud_repuesto_api_view(request):
    if not request.user.is_authenticated:
        return Response({'error': 'Debes iniciar sesión para enviar una solicitud.'}, status=status.HTTP_401_UNAUTHORIZED)

    correo = request.user.email or request.user.username
    usuario = Usuario.objects.filter(email__iexact=correo).first()
    if not usuario:
        return Response(
            {'error': 'Tu cuenta no tiene perfil de cliente. Inicia sesión con una cuenta de cliente (registrada en /registro).'},
            status=status.HTTP_400_BAD_REQUEST
        )
    pieza = (request.data.get('pieza') or '').strip()
    if not pieza:
        return Response({'error': 'Indica la pieza que necesitas.'}, status=status.HTTP_400_BAD_REQUEST)

    urgencia = request.data.get('urgencia') or 'MEDIA'
    if urgencia not in ('BAJA', 'MEDIA', 'ALTA'):
        urgencia = 'MEDIA'

    SolicitudEspecial.objects.create(
        usuario=usuario,
        vin_vehiculo=(request.data.get('vehiculo') or '').strip().upper()[:17],
        pieza_requerida=pieza[:200],
        nivel_urgencia=urgencia,
        estado='PENDIENTE',
    )
    return Response({'mensaje': 'Solicitud recibida.'}, status=status.HTTP_201_CREATED)


class CheckoutError(Exception):
    pass


def _usuario_de_sesion(request):
    if not request.user.is_authenticated:
        return None
    correo = request.user.email or request.user.username
    return Usuario.objects.filter(email__iexact=correo).first()

@api_view(['GET'])
@permission_classes([AllowAny])
def mi_perfil_api_view(request):
    """Datos del cliente con sesión iniciada, para autocompletar el checkout."""
    usuario = _usuario_de_sesion(request)
    if not usuario:
        return Response({'error': 'Sin sesión de cliente.'}, status=status.HTTP_401_UNAUTHORIZED)

    partes = usuario.nombre_completo.split(' ', 1)
    nombre = request.user.first_name or partes[0]
    apellido = request.user.last_name or (partes[1] if len(partes) > 1 else '')

    rut = (usuario.rut or '').replace('.', '').replace('-', '')
    rut = f'{rut[:-1]}-{rut[-1]}' if len(rut) > 1 else rut

    digitos = ''.join(c for c in (usuario.telefono or '') if c.isdigit())

    return Response({
        'email': usuario.email,
        'nombre': nombre,
        'apellido': apellido,
        'rut': rut,
        'telefono': digitos[-8:],  # el formulario ya muestra "+56 9" aparte
    })


@api_view(['GET'])
@permission_classes([AllowAny])
def tarifas_despacho_api_view(request):
    tarifas = TarifaDespacho.objects.order_by('region', 'comuna').values(
        'id', 'region', 'comuna', 'costo_base_kg', 'dias_habiles_estimados'
    )
    return Response(list(tarifas))


def _rut_valido(rut):
    """Valida un RUT chileno (Módulo 11). Devuelve el RUT normalizado o None."""
    limpio = re.sub(r'[.\-\s]', '', rut or '').upper()
    if not re.fullmatch(r'\d{7,8}[\dK]', limpio):
        return None
    cuerpo, dv = limpio[:-1], limpio[-1]
    suma, factor = 0, 2
    for digito in reversed(cuerpo):
        suma += int(digito) * factor
        factor = 2 if factor == 7 else factor + 1
    resto = 11 - (suma % 11)
    esperado = '0' if resto == 11 else 'K' if resto == 10 else str(resto)
    return f'{cuerpo}-{dv}' if dv == esperado else None


@api_view(['POST'])
@permission_classes([AllowAny])
def checkout_api_view(request):
    """
    Cotiza (simular=true) o confirma un pedido. Se puede comprar sin cuenta (invitado).
    Si hay sesión de cliente, el pedido se asocia a su usuario.
    Precios y stock se leen de la base de datos, nunca del navegador.
    """
    usuario = _usuario_de_sesion(request)  # None si es invitado

    items = request.data.get('items') or []
    simular = bool(request.data.get('simular'))
    tarifa = TarifaDespacho.objects.filter(id=request.data.get('tarifa_id')).first()
    cliente = request.data.get('cliente') or {}

    if not items:
        return Response({'error': 'Tu carrito está vacío.'}, status=status.HTTP_400_BAD_REQUEST)
    if not tarifa:
        return Response({'error': 'Elige la comuna de despacho.'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        with transaction.atomic():
            # --- Datos del comprador (solo al confirmar) ---
            if not simular:
                email = (cliente.get('email') or '').strip()
                nombre = (cliente.get('nombre') or '').strip()
                apellido = (cliente.get('apellido') or '').strip()
                telefono = re.sub(r'\D', '', cliente.get('telefono') or '')
                calle = (cliente.get('direccion') or '').strip()
                rut = _rut_valido(cliente.get('rut'))

                try:
                    validate_email(email)
                except ValidationError:
                    raise CheckoutError('Ingresa un correo válido.')
                if not nombre or not apellido:
                    raise CheckoutError('Ingresa nombre y apellido de quien recibe.')
                if not rut:
                    raise CheckoutError('El RUT no es válido.')
                if len(telefono) != 8:
                    raise CheckoutError('El teléfono debe tener 8 dígitos después del +56 9.')
                if len(calle) < 4:
                    raise CheckoutError('Ingresa la dirección de despacho (calle y número).')

            # --- Productos, stock y totales ---
            ids = [int(i.get('id')) for i in items]
            repuestos = {
                r.id: r for r in Repuesto.objects.select_for_update().filter(id__in=ids, activo=True)
            }

            lineas = []
            subtotal = 0
            peso_total = Decimal('0')
            for i in items:
                r = repuestos.get(int(i.get('id')))
                cantidad = int(i.get('cantidad') or 0)
                if not r or cantidad < 1:
                    raise CheckoutError('Un producto de tu carrito ya no está disponible.')
                if cantidad > r.stock_disponible:
                    raise CheckoutError(f'Stock insuficiente de "{r.nombre}": quedan {r.stock_disponible}.')
                subtotal += r.precio_unitario * cantidad
                peso_total += r.peso_kg * cantidad
                lineas.append((r, cantidad))

            costo_envio = tarifa.costo_base_kg * max(1, math.ceil(peso_total))
            total = subtotal + costo_envio
            resumen = {
                'subtotal': subtotal,
                'costo_envio': costo_envio,
                'monto_total': total,
                'dias_habiles': tarifa.dias_habiles_estimados,
            }

            if simular:
                return Response(resumen)

            complemento = (cliente.get('complemento') or '').strip()
            pedido = Pedido.objects.create(
                usuario=usuario,
                tarifa=tarifa,
                email_cliente=email.lower(),
                nombre_cliente=nombre[:80],
                apellido_cliente=apellido[:80],
                rut_cliente=rut,
                telefono_cliente='+569' + telefono,
                patente_vin=(cliente.get('patente') or '').strip().upper()[:30],
                direccion_calle=f'{calle}, {tarifa.comuna}, {tarifa.region}'[:255],
                direccion_complemento=complemento[:120],
                instrucciones_entrega=(cliente.get('instrucciones') or '').strip()[:255],
                subtotal=subtotal,
                costo_envio=costo_envio,
                monto_total=total,
                estado='PENDIENTE_PAGO',
            )
            for r, cantidad in lineas:
                DetallePedido.objects.create(
                    pedido=pedido, repuesto=r, cantidad=cantidad, precio_historico=r.precio_unitario
                )
            # El stock se descuenta cuando Webpay confirma el pago (webpay_retorno_view)

            # Pedimos el token a Webpay. Si falla, se deshace el pedido completo.
            try:
                resp = requests.post(
                    WEBPAY_HOST + WEBPAY_API,
                    headers=WEBPAY_HEADERS,
                    timeout=20,
                    json={
                        'buy_order': f'RS{pedido.id}',
                        'session_id': f'S{pedido.id}',
                        'amount': total,
                        'return_url': f'{BACKEND_URL}/api/webpay/retorno/',
                    },
                )
                resp.raise_for_status()
                pago = resp.json()
            except (requests.RequestException, ValueError):
                raise CheckoutError('No pudimos iniciar el pago con Webpay. Intenta nuevamente.')

            TransaccionPago.objects.create(
                pedido=pedido,
                token_pasarela=pago['token'],
                metodo_pago='WEBPAY',
                monto_pagado=total,
                estado_pago='INICIADO',
            )

            resumen['pedido_id'] = pedido.id
            resumen['webpay_url'] = pago['url']
            resumen['webpay_token'] = pago['token']
            return Response(resumen, status=status.HTTP_201_CREATED)

    except CheckoutError as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    except (TypeError, ValueError):
        return Response({'error': 'Los datos del carrito no son válidos.'}, status=status.HTTP_400_BAD_REQUEST)


def _volver_al_sitio(estado, pedido_id=None, monto=None):
    q = {'estado': estado}
    if pedido_id:
        q['pedido'] = pedido_id
    if monto is not None:
        q['monto'] = monto
    return HttpResponseRedirect(f'{FRONTEND_URL}/pago-resultado?{urlencode(q)}')


@csrf_exempt
def webpay_retorno_view(request):
    """
    Webpay devuelve aquí al cliente (por GET o POST) después de pagar o anular.
    Confirma el pago con Transbank y redirige al sitio con el resultado.
    """
    datos = {**request.GET.dict(), **request.POST.dict()}
    token = datos.get('token_ws')

    # Sin token_ws: el cliente anuló el pago o venció el tiempo (llegan TBK_TOKEN, TBK_ORDEN_COMPRA...)
    if not token:
        pago = TransaccionPago.objects.select_related('pedido').filter(
            token_pasarela=datos.get('TBK_TOKEN', '')
        ).first()
        if pago and pago.estado_pago == 'INICIADO':
            pago.estado_pago = 'ANULADO'
            pago.save(update_fields=['estado_pago'])
            pago.pedido.estado = 'ANULADO'
            pago.pedido.save(update_fields=['estado'])
            return _volver_al_sitio('cancelado', pago.pedido.id)
        return _volver_al_sitio('cancelado')

    pago = TransaccionPago.objects.select_related('pedido').filter(token_pasarela=token).first()
    if not pago:
        return _volver_al_sitio('error')
    pedido = pago.pedido

    # Si ya se procesó (el cliente recargó la página), no se confirma dos veces
    if pago.estado_pago != 'INICIADO':
        ok = pago.estado_pago == 'APROBADO'
        return _volver_al_sitio('ok' if ok else 'rechazado', pedido.id, pedido.monto_total)

    # Confirmar con Webpay
    try:
        r = requests.put(f'{WEBPAY_HOST}{WEBPAY_API}/{token}', headers=WEBPAY_HEADERS, timeout=20)
        r.raise_for_status()
        res = r.json()
    except (requests.RequestException, ValueError):
        return _volver_al_sitio('error', pedido.id)

    aprobado = (
        res.get('status') == 'AUTHORIZED'
        and res.get('response_code') == 0
        and res.get('amount') == pedido.monto_total
    )

    with transaction.atomic():
        if aprobado:
            detalles = list(pedido.detallepedido_set.all())
            repuestos = {
                r.id: r for r in Repuesto.objects.select_for_update()
                .filter(id__in=[d.repuesto_id for d in detalles])
            }
            faltante = False
            for d in detalles:
                rep = repuestos[d.repuesto_id]
                if rep.stock_disponible < d.cantidad:
                    faltante = True  # alguien compró lo mismo mientras pagaba
                rep.stock_disponible = max(0, rep.stock_disponible - d.cantidad)
                rep.save(update_fields=['stock_disponible'])
            pedido.estado = 'REVISAR_STOCK' if faltante else 'PAGADO'
        else:
            pedido.estado = 'RECHAZADO'
        pedido.save(update_fields=['estado'])

        pago.estado_pago = 'APROBADO' if aprobado else 'RECHAZADO'
        pago.codigo_autorizacion = res.get('authorization_code')
        pago.metodo_pago = f"WEBPAY {res.get('payment_type_code') or ''}".strip()
        pago.save()

    return _volver_al_sitio('ok' if aprobado else 'rechazado', pedido.id, pedido.monto_total)

# --- Carga masiva de repuestos por CSV (solo administradores) ---

COLUMNAS_CSV = [
    'nombre', 'marca', 'categoria', 'subcategoria', 'condicion', 'precio', 'stock_disponible',
    'codigo_oem', 'descripcion', 'intervalo_cambio_km', 'intervalo_cambio_meses', 'sku',
]
COLUMNAS_OBLIGATORIAS_CSV = set(COLUMNAS_CSV) - {'sku'}
MAX_BYTES_CSV = 1024 * 1024
MAX_FILAS_CSV = 2000


def _entero_csv(texto, campo, errores, obligatorio=False, minimo=0):
    """Entero desde el CSV. Acepta "5000", "5.000" y "$5.000". Devuelve None si viene vacío."""
    texto = (texto or '').strip()
    if not texto:
        if obligatorio:
            errores.append(f'{campo} es obligatorio')
        return None
    if not re.fullmatch(r'\$?\s*(\d+|\d{1,3}(\.\d{3})+)', texto):
        errores.append(f'{campo} debe ser un número entero ("{texto}")')
        return None
    valor = int(re.sub(r'\D', '', texto))
    if valor < minimo:
        errores.append(f'{campo} debe ser mayor o igual a {minimo}')
        return None
    return valor


def _validar_fila_csv(fila, categorias, skus_del_archivo):
    """Devuelve (Repuesto sin guardar, lista de errores) para una fila del CSV."""
    errores = []
    dato = lambda k: (fila.get(k) or '').strip()

    nombre = dato('nombre')
    if not nombre:
        errores.append('nombre es obligatorio')

    categoria = subcategoria = None
    cat = categorias.get(clave_alfabetica(dato('categoria')))
    if not cat:
        errores.append(f'la categoría "{dato("categoria")}" no existe')
    else:
        categoria, subcategorias = cat
        subcategoria = subcategorias.get(clave_alfabetica(dato('subcategoria')))
        if not subcategoria:
            errores.append(f'la subcategoría "{dato("subcategoria")}" no existe en "{categoria.nombre}"')

    condicion = dato('condicion').upper()
    if condicion not in dict(Repuesto.CONDICION_CHOICES):
        errores.append(f'condición inválida ("{dato("condicion")}"): usa NUEVO, USADO o REACONDICIONADO')

    precio = _entero_csv(dato('precio'), 'precio', errores, obligatorio=True)
    stock = _entero_csv(dato('stock_disponible'), 'stock_disponible', errores, obligatorio=True)
    km = _entero_csv(dato('intervalo_cambio_km'), 'intervalo_cambio_km', errores, minimo=1)
    meses = _entero_csv(dato('intervalo_cambio_meses'), 'intervalo_cambio_meses', errores, minimo=1)

    sku = dato('sku').upper()
    if sku:
        if sku in skus_del_archivo:
            errores.append(f'el SKU {sku} está repetido en el archivo')
        skus_del_archivo.add(sku)

    repuesto = Repuesto(
        nombre=nombre,
        marca_fabricante=dato('marca') or 'Genérico',
        categoria=categoria,
        subcategoria=subcategoria,
        condicion=condicion,
        precio_unitario=precio,
        stock_disponible=stock,
        codigo_oem=dato('codigo_oem') or None,
        descripcion=dato('descripcion') or None,
        intervalo_cambio_km=km,
        intervalo_cambio_meses=meses,
        sku=sku,
    )
    if not errores:
        # Largo de textos y SKU ya existente en la base
        try:
            repuesto.full_clean(exclude=['sku'] if not sku else [])
        except ValidationError as e:
            mensajes = {'sku': 'ya existe un repuesto con ese SKU'}
            errores += [mensajes.get(campo) or f'{campo}: {" ".join(m)}' for campo, m in e.message_dict.items()]
    return repuesto, errores


@api_view(['POST'])
@permission_classes([IsAdminUser])
def carga_masiva_repuestos_api_view(request):
    """
    Recibe un CSV (campo "archivo") y un modo: "validar" (no guarda nada) o "importar"
    (crea en una sola transacción todas las filas válidas). Devuelve el informe por fila.
    """
    modo = request.data.get('modo', 'validar')
    archivo = request.FILES.get('archivo')
    if modo not in ('validar', 'importar'):
        return Response({'error': 'El modo debe ser "validar" o "importar".'}, status=status.HTTP_400_BAD_REQUEST)
    if not archivo:
        return Response({'error': 'Adjunta un archivo CSV.'}, status=status.HTTP_400_BAD_REQUEST)
    if archivo.size > MAX_BYTES_CSV:
        return Response({'error': 'El archivo supera 1 MB.'}, status=status.HTTP_400_BAD_REQUEST)

    contenido = archivo.read()
    try:
        texto = contenido.decode('utf-8-sig')
    except UnicodeDecodeError:
        texto = contenido.decode('cp1252', errors='replace')  # CSV guardado por Excel en Windows

    # Excel en español separa con punto y coma
    primera_linea = texto.split('\n', 1)[0]
    separador = ';' if primera_linea.count(';') > primera_linea.count(',') else ','
    lector = csv.DictReader(io.StringIO(texto), delimiter=separador)
    lector.fieldnames = [(c or '').strip().lower() for c in (lector.fieldnames or [])]

    faltantes = [c for c in COLUMNAS_CSV if c in COLUMNAS_OBLIGATORIAS_CSV and c not in lector.fieldnames]
    if faltantes:
        return Response({'error': 'Faltan columnas: ' + ', '.join(faltantes)}, status=status.HTTP_400_BAD_REQUEST)

    categorias = {
        clave_alfabetica(c.nombre): (c, {clave_alfabetica(s.nombre): s for s in c.subcategorias.all()})
        for c in Categoria.objects.prefetch_related('subcategorias')
    }

    # Un repuesto ya existe si coincide nombre, marca y código OEM (sin distinguir mayúsculas ni tildes)
    clave_repuesto = lambda nombre, marca, oem: (clave_alfabetica(nombre), clave_alfabetica(marca), clave_alfabetica(oem))
    existentes = {
        clave_repuesto(*r) for r in Repuesto.objects.values_list('nombre', 'marca_fabricante', 'codigo_oem')
    }

    filas, validos, skus_del_archivo = [], [], set()
    try:
        for fila in lector:
            if not any((v or '').strip() for v in fila.values() if isinstance(v, str)):
                continue  # línea vacía
            if len(filas) >= MAX_FILAS_CSV:
                return Response({'error': f'El archivo supera {MAX_FILAS_CSV} filas.'}, status=status.HTTP_400_BAD_REQUEST)
            repuesto, errores = _validar_fila_csv(fila, categorias, skus_del_archivo)
            item = {'fila': lector.line_num, 'nombre': repuesto.nombre, 'sku': repuesto.sku,
                    'ok': not errores, 'estado': 'ok' if not errores else 'error', 'motivo': '; '.join(errores)}
            filas.append(item)
            if errores:
                continue
            clave = clave_repuesto(repuesto.nombre, repuesto.marca_fabricante, repuesto.codigo_oem)
            if clave in existentes:
                # Ya está en el catálogo (o más arriba en este mismo archivo): no se importa
                item.update(ok=False, estado='duplicada',
                            motivo='ya existe un repuesto con el mismo nombre, marca y código OEM')
                continue
            existentes.add(clave)
            validos.append((repuesto, item))
    except csv.Error as e:
        return Response({'error': f'El CSV está mal formado: {e}'}, status=status.HTTP_400_BAD_REQUEST)

    if not filas:
        return Response({'error': 'El archivo no tiene filas de datos.'}, status=status.HTTP_400_BAD_REQUEST)

    creadas = 0
    if modo == 'importar' and validos:
        try:
            with transaction.atomic():
                for repuesto, item in validos:
                    repuesto.save()  # genera el SKU si viene vacío
                    item['sku'] = repuesto.sku
                creadas = len(validos)
        except IntegrityError:
            return Response(
                {'error': 'Otro usuario guardó un repuesto con uno de estos SKU mientras se importaba. '
                          'No se guardó nada: valida e importa nuevamente.'},
                status=status.HTTP_409_CONFLICT,
            )

    return Response({
        'modo': modo,
        'total': len(filas),
        'validas': len(validos),
        'duplicadas': sum(f['estado'] == 'duplicada' for f in filas),
        'con_error': sum(f['estado'] == 'error' for f in filas),
        'creadas': creadas,
        'filas': filas,
    })

# --- Resumen del panel de administración (solo administradores) ---

ZONA_CHILE = ZoneInfo('America/Santiago')
# Días hacia atrás desde hoy (incluido). None = desde la primera venta.
PERIODOS_RESUMEN = {'hoy': 0, '7d': 6, '30d': 29, 'todo': None}


@api_view(['GET'])
@permission_classes([IsAdminUser])
def resumen_admin_api_view(request):
    periodo = request.query_params.get('periodo', '7d')
    if periodo not in PERIODOS_RESUMEN:
        return Response({'error': 'Período inválido. Usa hoy, 7d, 30d o todo.'}, status=status.HTTP_400_BAD_REQUEST)

    hoy = timezone.localdate(timezone=ZONA_CHILE)
    pedidos = Pedido.objects.all()
    dias = PERIODOS_RESUMEN[periodo]
    if dias is None:
        primera = pedidos.filter(estado='PAGADO').order_by('fecha_creacion').first()
        desde = timezone.localdate(primera.fecha_creacion, ZONA_CHILE) if primera else hoy
    else:
        desde = hoy - timedelta(days=dias)
        pedidos = pedidos.filter(fecha_creacion__gte=datetime.combine(desde, time.min, tzinfo=ZONA_CHILE))
    pagados = pedidos.filter(estado='PAGADO')

    totales = pagados.aggregate(ventas=Sum('monto_total'), cantidad=Count('id'))
    ventas = totales['ventas'] or 0

    por_dia = {
        dia: (total, cantidad)
        for dia, total, cantidad in pagados
        .annotate(dia=TruncDate('fecha_creacion', tzinfo=ZONA_CHILE))
        .values('dia').annotate(total=Sum('monto_total'), cantidad=Count('id'))
        .values_list('dia', 'total', 'cantidad')
    }
    ventas_por_dia = []
    for i in range((hoy - desde).days + 1):
        dia = desde + timedelta(days=i)
        total, cantidad = por_dia.get(dia, (0, 0))
        ventas_por_dia.append({'fecha': dia.isoformat(), 'total': total, 'pedidos': cantidad})

    mas_vendidos = (
        DetallePedido.objects.filter(pedido__in=pagados)
        .values('repuesto_id', 'repuesto__sku', 'repuesto__nombre')
        .annotate(unidades=Sum('cantidad'), total=Sum(F('cantidad') * F('precio_historico')))
        .order_by('-unidades', '-total')[:5]
    )

    activos = Repuesto.objects.filter(activo=True)
    critico = activos.filter(stock_disponible__gt=0, stock_disponible__lte=STOCK_CRITICO).order_by('stock_disponible', 'nombre')
    agotados = activos.filter(stock_disponible__lte=0).order_by('nombre')
    campos = ('id', 'sku', 'nombre', 'stock_disponible')

    return Response({
        'periodo': periodo,
        'desde': desde.isoformat(),
        'hasta': hoy.isoformat(),
        'ventas_totales': ventas,
        'pedidos_pagados': totales['cantidad'],
        'ticket_promedio': round(ventas / totales['cantidad']) if totales['cantidad'] else 0,
        'pedidos_por_estado': dict(pedidos.values_list('estado').annotate(n=Count('id')).order_by()),
        'ventas_por_dia': ventas_por_dia,
        'mas_vendidos': [
            {'id': m['repuesto_id'], 'sku': m['repuesto__sku'], 'nombre': m['repuesto__nombre'],
             'unidades': m['unidades'], 'total': m['total']}
            for m in mas_vendidos
        ],
        'stock_critico': {'cantidad': critico.count(), 'items': list(critico.values(*campos)[:10])},
        'agotados': {'cantidad': agotados.count(), 'items': list(agotados.values(*campos)[:10])},
        'solicitudes_pendientes': SolicitudEspecial.objects.filter(estado='PENDIENTE').count(),
    })
