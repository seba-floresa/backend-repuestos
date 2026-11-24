import json
from rest_framework import serializers
from .models import (
    Repuesto,
    Categoria,
    Subcategoria,
    Vehiculo,
    CompatibilidadVehicular,
    Pedido,
    DetallePedido,
    TransaccionPago,
    SolicitudEspecial,
)


class CategoriaSerializer(serializers.ModelSerializer):
    # Acepta "fil" y lo guarda como "FIL"
    prefijo_sku = serializers.RegexField(
        r'^[A-Za-z]{3}$', required=False, allow_blank=True,
        error_messages={'invalid': 'El prefijo debe tener 3 letras (ej: FIL).'},
    )

    class Meta:
        model = Categoria
        fields = '__all__'

    def validate_prefijo_sku(self, valor):
        return valor.upper()


class SubcategoriaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Subcategoria
        fields = '__all__'




class RepuestoSerializer(serializers.ModelSerializer):
    # Traducción de campos entre Angular (precio, stock) y Django (precio_unitario, stock_disponible)
    precio = serializers.IntegerField(source='precio_unitario')
    stock = serializers.IntegerField(source='stock_disponible')

    # Si el formulario multipart no envía "activo", DRF lo interpreta como False.
    # Con default=True los repuestos nuevos quedan visibles en la tienda.
    activo = serializers.BooleanField(default=True)

    # Campos de solo lectura para mostrar nombres y cargar edición en Angular
    categoria_id = serializers.IntegerField(source='categoria.id', read_only=True)
    categoria_nombre = serializers.CharField(source='categoria.nombre', read_only=True)
    subcategoria_id = serializers.SerializerMethodField()
    subcategoria_nombre = serializers.SerializerMethodField()
    vehiculos = serializers.SerializerMethodField()
    vehiculos_nombres = serializers.SerializerMethodField()

    class Meta:
        model = Repuesto
        fields = [
            'id',
            'sku',
            'codigo_oem',
            'nombre',
            'descripcion',
            'intervalo_cambio_km',
            'intervalo_cambio_meses',
            'marca_fabricante',
            'condicion',
            'detalle_desgaste',
            'urls_fotos_reales',
            'peso_kg',
            'categoria',
            'categoria_id',
            'categoria_nombre',
            'subcategoria',
            'subcategoria_id',
            'subcategoria_nombre',
            'precio',
            'stock',
            'imagen',
            'activo',
            'vehiculos',
            'vehiculos_nombres',
        ]
        # SKU vacío: el modelo genera uno (RS-FIL-0001). Se mantiene la validación de único.
        extra_kwargs = {'sku': {'required': False, 'allow_blank': True}}

    def get_subcategoria_id(self, obj):
        return obj.subcategoria.id if obj.subcategoria else None

    def get_subcategoria_nombre(self, obj):
        return obj.subcategoria.nombre if obj.subcategoria else ''

    def get_vehiculos(self, obj):
        return list(
            CompatibilidadVehicular.objects.filter(repuesto=obj).values_list('vehiculo_id', flat=True)
        )

    def get_vehiculos_nombres(self, obj):
        compatibilidades = CompatibilidadVehicular.objects.filter(repuesto=obj).select_related('vehiculo')
        nombres = []
        for c in compatibilidades:
            v = c.vehiculo
            rango = f"{v.anio_inicio}-{v.anio_fin}" if v.anio_fin else f"{v.anio_inicio}+"
            motor = f"(Motor {v.motorizacion})" if v.motorizacion else ""
            nombres.append(f"{v.marca} {v.modelo} {rango} {motor}".strip())
        return nombres

    def _guardar_compatibilidades(self, repuesto):
        request = self.context.get('request')
        if not request or 'vehiculos' not in request.data:
            return

        vehiculos_raw = request.data.get('vehiculos')
        try:
            ids = json.loads(vehiculos_raw) if isinstance(vehiculos_raw, str) else vehiculos_raw
        except (json.JSONDecodeError, TypeError):
            ids = []

        CompatibilidadVehicular.objects.filter(repuesto=repuesto).delete()
        for v_id in ids:
            vehiculo = Vehiculo.objects.filter(id=v_id).first()
            if vehiculo:
                CompatibilidadVehicular.objects.create(
                    repuesto=repuesto,
                    vehiculo=vehiculo,
                    anio_desde=vehiculo.anio_inicio,
                    # Si anio_fin es nulo, guardamos el mismo anio_inicio (o puedes poner un año genérico como 2050)
                    anio_hasta=vehiculo.anio_fin if vehiculo.anio_fin else vehiculo.anio_inicio,
                )

    def create(self, validated_data):
        repuesto = super().create(validated_data)
        self._guardar_compatibilidades(repuesto)
        return repuesto

    def update(self, instance, validated_data):
        repuesto = super().update(instance, validated_data)
        self._guardar_compatibilidades(repuesto)
        return repuesto


class PedidoSerializer(serializers.ModelSerializer):
    """Fila de la lista de pedidos del panel (solo administradores)."""
    estado_nombre = serializers.CharField(source='get_estado_display', read_only=True)

    class Meta:
        model = Pedido
        fields = ['id', 'fecha_creacion', 'nombre_cliente', 'apellido_cliente', 'email_cliente',
                  'monto_total', 'estado', 'estado_nombre']


class DetallePedidoSerializer(serializers.ModelSerializer):
    sku = serializers.CharField(source='repuesto.sku', read_only=True)
    nombre = serializers.CharField(source='repuesto.nombre', read_only=True)
    subtotal = serializers.SerializerMethodField()

    class Meta:
        model = DetallePedido
        fields = ['id', 'repuesto', 'sku', 'nombre', 'cantidad', 'precio_historico', 'subtotal']

    def get_subtotal(self, obj):
        return obj.cantidad * obj.precio_historico


class TransaccionPagoSerializer(serializers.ModelSerializer):
    # Sin token_pasarela: no se necesita para gestionar el pedido
    class Meta:
        model = TransaccionPago
        fields = ['id', 'estado_pago', 'monto_pagado', 'metodo_pago', 'codigo_autorizacion', 'fecha_transaccion']


class PedidoDetalleSerializer(PedidoSerializer):
    productos = DetallePedidoSerializer(source='detallepedido_set', many=True, read_only=True)
    pagos = TransaccionPagoSerializer(source='transaccionpago_set', many=True, read_only=True)
    comuna = serializers.CharField(source='tarifa.comuna', default='', read_only=True)
    region = serializers.CharField(source='tarifa.region', default='', read_only=True)
    siguiente_estado = serializers.SerializerMethodField()

    class Meta(PedidoSerializer.Meta):
        fields = PedidoSerializer.Meta.fields + [
            'rut_cliente', 'telefono_cliente', 'patente_vin',
            'direccion_calle', 'direccion_complemento', 'instrucciones_entrega', 'comuna', 'region',
            'empresa_courier', 'codigo_seguimiento',
            'subtotal', 'costo_envio', 'productos', 'pagos', 'siguiente_estado',
        ]

    def get_siguiente_estado(self, obj):
        return Pedido.TRANSICIONES.get(obj.estado)


class SolicitudEspecialSerializer(serializers.ModelSerializer):
    estado_nombre = serializers.CharField(source='get_estado_display', read_only=True)
    cliente_nombre = serializers.CharField(source='usuario.nombre_completo', read_only=True)
    cliente_email = serializers.CharField(source='usuario.email', read_only=True)
    cliente_telefono = serializers.CharField(source='usuario.telefono', read_only=True, default='')
    valor_cotizado = serializers.IntegerField(min_value=0, required=False, allow_null=True)

    class Meta:
        model = SolicitudEspecial
        fields = ['id', 'fecha_solicitud', 'cliente_nombre', 'cliente_email', 'cliente_telefono',
                  'vin_vehiculo', 'pieza_requerida', 'nivel_urgencia',
                  'estado', 'estado_nombre', 'valor_cotizado', 'comentario_admin']
        # Lo que escribe el cliente no se edita desde el panel
        read_only_fields = ['vin_vehiculo', 'pieza_requerida', 'nivel_urgencia']


class VehiculoSerializer(serializers.ModelSerializer):
    nombre = serializers.SerializerMethodField()

    class Meta:
        model = Vehiculo
        fields = ['id', 'marca', 'modelo', 'anio_inicio', 'anio_fin', 'motorizacion', 'nombre']

    def validate(self, data):
        inicio = data.get('anio_inicio', getattr(self.instance, 'anio_inicio', None))
        fin = data.get('anio_fin', getattr(self.instance, 'anio_fin', None))
        if inicio and fin and fin < inicio:
            raise serializers.ValidationError({'anio_fin': 'El año final no puede ser anterior al año de inicio.'})
        return data

    def get_nombre(self, obj):
        rango = f"{obj.anio_inicio}-{obj.anio_fin}" if obj.anio_fin else f"{obj.anio_inicio}+"
        motor = f"(Motor {obj.motorizacion})" if obj.motorizacion else ""
        return f"{obj.marca} {obj.modelo} {rango} {motor}".strip()