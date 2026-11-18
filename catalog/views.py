from rest_framework import viewsets, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAdminUser
from django.contrib.auth import authenticate
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny


from .models import Repuesto, Categoria, Subcategoria, Vehiculo, Pedido
from .serializers import (
    RepuestoSerializer,
    CategoriaSerializer,
    SubcategoriaSerializer,
    VehiculoSerializer,
    PedidoSerializer,
)
from .services.vin_service import MockBuscadorVehiculo

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
def register_api_view(request):
    from django.contrib.auth.models import User
    from django.contrib.auth.hashers import make_password
    from .models import Usuario
    
    rut = request.data.get('rut', '').strip()
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

class CategoriaViewSet(viewsets.ModelViewSet):
    queryset = Categoria.objects.all()
    serializer_class = CategoriaSerializer


class SubcategoriaViewSet(viewsets.ModelViewSet):
    queryset = Subcategoria.objects.all()
    serializer_class = SubcategoriaSerializer


class VehiculoViewSet(viewsets.ModelViewSet):
    queryset = Vehiculo.objects.all().order_by('marca', 'modelo', 'anio_inicio')
    serializer_class = VehiculoSerializer

class RepuestoViewSet(viewsets.ModelViewSet):
    queryset = Repuesto.objects.all().order_by('-id')
    serializer_class = RepuestoSerializer
    
    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            return []
        return [IsAdminUser()]


class PedidoViewSet(viewsets.ModelViewSet):
    queryset = Pedido.objects.all()
    serializer_class = PedidoSerializer


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