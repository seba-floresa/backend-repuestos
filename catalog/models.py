from django.core.validators import RegexValidator
from django.db import models, transaction, IntegrityError
import unicodedata
import uuid

# 1. Usuarios
class Usuario(models.Model):
    rut = models.CharField(max_length=12, unique=True)
    nombre_completo = models.CharField(max_length=120)
    email = models.EmailField(max_length=150, unique=True)
    password_hash = models.CharField(max_length=255)
    telefono = models.CharField(max_length=20, blank=True, null=True)
    rol = models.CharField(max_length=20)
    fecha_registro = models.DateTimeField(auto_now_add=True)

    def __str__(self): return self.nombre_completo

# 2. Vehículos (Catálogo base de marcas y modelos)
class Vehiculo(models.Model):
    # Ya no necesitamos patente ni vin aquí
    marca = models.CharField(max_length=50, db_index=True)
    modelo = models.CharField(max_length=80, db_index=True)
    anio_inicio = models.SmallIntegerField(db_index=True, default=2000) # Año en que empezó a fabricarse
    anio_fin = models.SmallIntegerField(blank=True, null=True) # Año en que dejó de fabricarse, si aplica
    motorizacion = models.CharField(max_length=50, blank=True, null=True)

    def __str__(self):
        rango = f"{self.anio_inicio}-{self.anio_fin}" if self.anio_fin else f"{self.anio_inicio}+"
        return f"{self.marca} {self.modelo} {rango}"

# 3. Vehículos específicos de los clientes
class VehiculoCliente(models.Model):
    usuario = models.ForeignKey(Usuario, on_delete=models.CASCADE, related_name='vehiculos')
    vehiculo_base = models.ForeignKey(Vehiculo, on_delete=models.RESTRICT)
    patente = models.CharField(max_length=10, unique=True, blank=True, null=True)
    vin = models.CharField(max_length=17, unique=True, blank=True, null=True)
    color = models.CharField(max_length=30, blank=True, null=True)
    
    def __str__(self):
        return f"{self.patente} - {self.vehiculo_base.marca} {self.vehiculo_base.modelo}"

# 4. Categorías
class Categoria(models.Model):
    nombre = models.CharField(max_length=80)
    descripcion = models.TextField(blank=True, null=True)
    # Prefijo del SKU automático (RS-FIL-0001). Vacío = 3 primeras letras del nombre.
    prefijo_sku = models.CharField(
        max_length=3, blank=True, default='',
        validators=[RegexValidator(r'^[A-Z]{3}$', 'El prefijo debe tener 3 letras mayúsculas (ej: FIL).')],
    )

    def __str__(self):
        return self.nombre

# 5. Subcategorías de Repuestos
class Subcategoria(models.Model):
    categoria = models.ForeignKey(Categoria, related_name='subcategorias', on_delete=models.CASCADE)
    nombre = models.CharField(max_length=80)

    def __str__(self):
        return f"{self.categoria.nombre} - {self.nombre}"

# 6. Repuestos (Productos)
class Repuesto(models.Model):
    CONDICION_CHOICES = [
        ('NUEVO', 'Nuevo'),
        ('USADO', 'Usado'),
        ('REACONDICIONADO', 'Reacondicionado'),
    ]

    categoria = models.ForeignKey(Categoria, on_delete=models.CASCADE)
    subcategoria = models.ForeignKey(Subcategoria, on_delete=models.SET_NULL, null=True, blank=True)
    sku = models.CharField(max_length=50, unique=True, blank=True)  # vacío = se genera al guardar
    nombre = models.CharField(max_length=150)
    marca_fabricante = models.CharField(max_length=80, default='Genérico')
    precio_unitario = models.IntegerField()
    peso_kg = models.DecimalField(max_digits=5, decimal_places=2, default=1.00)
    stock_disponible = models.IntegerField(default=0)
    stock_reservado = models.IntegerField(default=0)
    condicion = models.CharField(max_length=20, choices=CONDICION_CHOICES, default='NUEVO', db_index=True)
    detalle_desgaste = models.TextField(blank=True, null=True)
    imagen = models.ImageField(upload_to='products/', blank=True, null=True)
    urls_fotos_reales = models.JSONField(blank=True, null=True)
    activo = models.BooleanField(default=True)
    codigo_oem = models.CharField(max_length=50, blank=True, null=True, db_index=True)
    descripcion = models.TextField(blank=True, null=True)
    # Cada cuánto se recomienda cambiar la pieza (lo que ocurra primero)
    intervalo_cambio_km = models.PositiveIntegerField(blank=True, null=True)
    intervalo_cambio_meses = models.PositiveIntegerField(blank=True, null=True)

    def __str__(self):
        return f"{self.sku} - {self.nombre}"

    def save(self, *args, **kwargs):
        if self.sku:
            return super().save(*args, **kwargs)
        # SKU automático. Si otra carga simultánea toma el mismo correlativo,
        # el índice único lo rechaza y se reintenta con el siguiente.
        for _ in range(10):
            self.sku = siguiente_sku(self.categoria)
            try:
                with transaction.atomic():
                    return super().save(*args, **kwargs)
            except IntegrityError:
                if not Repuesto.objects.filter(sku=self.sku).exists():
                    raise  # el error no era por el SKU
        self.sku = ''
        raise IntegrityError('No se pudo generar un SKU único. Intenta nuevamente.')


def prefijo_categoria(categoria):
    """Prefijo de la categoría; si no tiene, 3 primeras letras del nombre sin tildes ("Filtros" -> "FIL")."""
    if categoria.prefijo_sku:
        return categoria.prefijo_sku
    texto = unicodedata.normalize('NFD', categoria.nombre or '')
    letras = ''.join(c for c in texto if c.isascii() and c.isalpha()).upper()
    return (letras + 'XXX')[:3]


def siguiente_sku(categoria):
    """RS-<prefijo>-<correlativo de 4 dígitos> (DES-0001 para desarmaduría), tras el número más alto ya usado."""
    letras = prefijo_categoria(categoria)
    prefijo = 'DES-' if letras == 'DES' else f'RS-{letras}-'
    numeros = [
        int(s[len(prefijo):])
        for s in Repuesto.objects.filter(sku__startswith=prefijo).values_list('sku', flat=True)
        if s[len(prefijo):].isdigit()
    ]
    return f'{prefijo}{max(numeros, default=0) + 1:04d}'

# 7. Compatibilidad Vehicular (Tabla intermedia explícita)
class CompatibilidadVehicular(models.Model):
    repuesto = models.ForeignKey(Repuesto, on_delete=models.CASCADE)
    vehiculo = models.ForeignKey(Vehiculo, on_delete=models.CASCADE)
    anio_desde = models.SmallIntegerField()
    anio_hasta = models.SmallIntegerField()
    notas_tecnicas = models.CharField(max_length=255, blank=True, null=True)

# 8. Reglas de Cross-Selling
class ReglaCrossSelling(models.Model):
    repuesto_origen = models.ForeignKey(Repuesto, related_name='sugerencias_origen', on_delete=models.CASCADE)
    repuesto_sugerido = models.ForeignKey(Repuesto, related_name='sugerencias_destino', on_delete=models.CASCADE)
    tipo_relacion = models.CharField(max_length=50)
    prioridad = models.SmallIntegerField(default=1)

# 9. Carrito de Compras
class Carrito(models.Model):
    usuario = models.OneToOneField(Usuario, on_delete=models.CASCADE)
    fecha_actualizacion = models.DateTimeField(auto_now=True)

# 10. Items del Carrito
class ItemCarrito(models.Model):
    carrito = models.ForeignKey(Carrito, on_delete=models.CASCADE)
    repuesto = models.ForeignKey(Repuesto, on_delete=models.CASCADE)
    cantidad = models.SmallIntegerField()
    precio_capturado = models.IntegerField()

# 11. Tarifas de Despacho
class TarifaDespacho(models.Model):
    region = models.CharField(max_length=80)
    comuna = models.CharField(max_length=80, unique=True)
    costo_base_kg = models.IntegerField()
    dias_habiles_estimados = models.SmallIntegerField()

# 12. Pedidos
class Pedido(models.Model):
    # Opcional: un invitado compra sin cuenta
    usuario = models.ForeignKey(Usuario, on_delete=models.SET_NULL, null=True, blank=True)
    tarifa = models.ForeignKey(TarifaDespacho, on_delete=models.SET_NULL, null=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    # Datos de contacto (el email permite asociar el historial al crear cuenta)
    email_cliente = models.EmailField(max_length=150, blank=True, default='', db_index=True)
    nombre_cliente = models.CharField(max_length=80, blank=True, default='')
    apellido_cliente = models.CharField(max_length=80, blank=True, default='')
    rut_cliente = models.CharField(max_length=12, blank=True, default='')
    telefono_cliente = models.CharField(max_length=20, blank=True, default='')
    patente_vin = models.CharField(max_length=30, blank=True, default='')

    direccion_calle = models.CharField(max_length=255)
    direccion_complemento = models.CharField(max_length=120, blank=True, default='')
    instrucciones_entrega = models.CharField(max_length=255, blank=True, default='')

    empresa_courier = models.CharField(max_length=50, blank=True, null=True)
    codigo_seguimiento = models.CharField(max_length=80, blank=True, null=True)
    subtotal = models.IntegerField()
    costo_envio = models.IntegerField()
    monto_total = models.IntegerField()
    estado = models.CharField(max_length=30, db_index=True)
# 13. Detalle del Pedido
class DetallePedido(models.Model):
    pedido = models.ForeignKey(Pedido, on_delete=models.CASCADE)
    repuesto = models.ForeignKey(Repuesto, on_delete=models.PROTECT)
    cantidad = models.SmallIntegerField()
    precio_historico = models.IntegerField()

# 14. Transacciones de Pago (Webpay)
class TransaccionPago(models.Model):
    pedido = models.ForeignKey(Pedido, on_delete=models.CASCADE)
    token_pasarela = models.CharField(max_length=120, unique=True)
    codigo_autorizacion = models.CharField(max_length=50, blank=True, null=True)
    metodo_pago = models.CharField(max_length=30, blank=True, null=True)
    monto_pagado = models.IntegerField()
    estado_pago = models.CharField(max_length=20)
    fecha_transaccion = models.DateTimeField(auto_now_add=True)

# 15. Documentos Tributarios (Boleta/Factura)
class DocumentoTributario(models.Model):
    pedido = models.OneToOneField(Pedido, on_delete=models.CASCADE)
    tipo_documento = models.CharField(max_length=20)
    folio_sii = models.IntegerField(unique=True, db_index=True)
    rut_receptor = models.CharField(max_length=12)
    monto_neto = models.IntegerField()
    monto_iva = models.IntegerField()
    monto_total = models.IntegerField()
    url_pdf_timbrado = models.CharField(max_length=255, blank=True, null=True)
    fecha_emision = models.DateTimeField(auto_now_add=True)

# 16. Solicitudes Especiales
class SolicitudEspecial(models.Model):
    usuario = models.ForeignKey(Usuario, on_delete=models.CASCADE)
    vin_vehiculo = models.CharField(max_length=17)
    pieza_requerida = models.CharField(max_length=200)
    nivel_urgencia = models.CharField(max_length=15)
    estado = models.CharField(max_length=20, db_index=True)
    valor_cotizado = models.IntegerField(blank=True, null=True)
    comentario_admin = models.TextField(blank=True, null=True)
    fecha_solicitud = models.DateTimeField(auto_now_add=True)

# 17. Sesiones de Chatbot IA
class SesionChatbot(models.Model):
    id_sesion = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    usuario = models.ForeignKey(Usuario, on_delete=models.SET_NULL, null=True, blank=True)
    fecha_inicio = models.DateTimeField(auto_now_add=True)
    contexto_vehiculo = models.CharField(max_length=100, blank=True, null=True)

# 18. Mensajes del Chatbot
class MensajeChatbot(models.Model):
    sesion = models.ForeignKey(SesionChatbot, on_delete=models.CASCADE)
    emisor = models.CharField(max_length=15)
    contenido = models.TextField()
    fecha_envio = models.DateTimeField(auto_now_add=True)