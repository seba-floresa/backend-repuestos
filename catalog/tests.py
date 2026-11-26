from django.test import TestCase

from .models import Categoria, Subcategoria


class OrdenCategoriasTest(TestCase):
    def test_categorias_y_subcategorias_ordenadas_sin_tildes_ni_mayusculas(self):
        for nombre in ['motor', 'Óptica', 'Frenos', 'aceites', 'Ébano']:
            Categoria.objects.create(nombre=nombre)
        cat = Categoria.objects.get(nombre='Frenos')
        for nombre in ['pastillas', 'Discos', 'Ábsorbedores']:
            Subcategoria.objects.create(categoria=cat, nombre=nombre)

        cats = [c['nombre'] for c in self.client.get('/api/categorias/').json()]
        subs = [s['nombre'] for s in self.client.get('/api/subcategorias/').json()]

        self.assertEqual(cats, ['aceites', 'Ébano', 'Frenos', 'motor', 'Óptica'])
        self.assertEqual(subs, ['Ábsorbedores', 'Discos', 'pastillas'])


from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile

from .models import Repuesto


class SkuAutomaticoTest(TestCase):
    def test_genera_correlativo_siguiendo_al_mas_alto(self):
        cat = Categoria.objects.create(nombre='Filtros')
        Repuesto.objects.create(categoria=cat, sku='RS-FIL-063', nombre='a', precio_unitario=1)
        r = Repuesto.objects.create(categoria=cat, nombre='b', precio_unitario=1)
        self.assertEqual(r.sku, 'RS-FIL-0064')
        r2 = Repuesto.objects.create(categoria=Categoria.objects.create(nombre='Óptica'), nombre='c', precio_unitario=1)
        self.assertEqual(r2.sku, 'RS-OPT-0001')

    def test_reintenta_si_el_correlativo_ya_fue_tomado(self):
        cat = Categoria.objects.create(nombre='Filtros')
        Repuesto.objects.create(categoria=cat, sku='RS-FIL-0001', nombre='a', precio_unitario=1)
        # Simula otra carga que tomó el mismo número: la 1a consulta devuelve un SKU ocupado
        from unittest import mock
        from . import models
        original = models.siguiente_sku
        llamadas = iter(['RS-FIL-0001'])
        with mock.patch.object(models, 'siguiente_sku', lambda c: next(llamadas, None) or original(c)):
            r = Repuesto.objects.create(categoria=cat, nombre='b', precio_unitario=1)
        self.assertEqual(r.sku, 'RS-FIL-0002')


class CargaMasivaTest(TestCase):
    CABECERA = 'nombre;marca;categoria;subcategoria;condicion;precio;stock_disponible;codigo_oem;descripcion;intervalo_cambio_km;intervalo_cambio_meses;sku\n'

    def setUp(self):
        cat = Categoria.objects.create(nombre='Filtros')
        Subcategoria.objects.create(categoria=cat, nombre='Filtro de Aceite')
        Repuesto.objects.create(categoria=cat, sku='RS-FIL-0001', nombre='existente', precio_unitario=1)
        self.admin = User.objects.create_user('admin', 'a@a.cl', 'x', is_staff=True)

    def enviar(self, filas, modo):
        archivo = SimpleUploadedFile('r.csv', (self.CABECERA + filas).encode('utf-8'))
        return self.client.post('/api/repuestos/carga-masiva/', {'archivo': archivo, 'modo': modo})

    FILAS = (
        'Filtro A;Bosch;filtros;FILTRO DE ACEITE;nuevo;$5.990;10;OEM1;Desc;10000;12;\n'
        'Filtro B;;Filtros;Filtro de Aceite;USADO;5000;0;;;;;RS-FIL-0001\n'          # SKU ya existe
        'Filtro C;;Frenos;Discos;NUEVO;-1;x;;;;;\n'                                  # varios errores
    )

    def test_solo_administradores(self):
        self.assertEqual(self.enviar(self.FILAS, 'validar').status_code, 403)

    def test_validar_no_guarda_e_informa_errores(self):
        self.client.force_login(self.admin)
        r = self.enviar(self.FILAS, 'validar').json()
        self.assertEqual((r['total'], r['validas'], r['creadas']), (3, 1, 0))
        self.assertIn('ya existe', r['filas'][1]['motivo'])
        self.assertIn('categoría "Frenos" no existe', r['filas'][2]['motivo'])
        self.assertIn('stock_disponible', r['filas'][2]['motivo'])
        self.assertEqual(Repuesto.objects.count(), 1)

    def test_importar_crea_solo_las_validas(self):
        self.client.force_login(self.admin)
        r = self.enviar(self.FILAS, 'importar').json()
        self.assertEqual(r['creadas'], 1)
        nuevo = Repuesto.objects.get(nombre='Filtro A')
        self.assertEqual((nuevo.sku, nuevo.precio_unitario, nuevo.intervalo_cambio_km), ('RS-FIL-0002', 5990, 10000))
        self.assertEqual(r['filas'][0]['sku'], 'RS-FIL-0002')

from .models import Pedido


class PermisosPedidosTest(TestCase):
    def test_pedidos_solo_para_administradores(self):
        self.assertEqual(self.client.get('/api/pedidos/').status_code, 403)
        cliente = User.objects.create_user('cliente', 'c@c.cl', 'x')
        self.client.force_login(cliente)
        self.assertEqual(self.client.get('/api/pedidos/').status_code, 403)
        self.client.force_login(User.objects.create_user('admin', 'a@a.cl', 'x', is_staff=True))
        self.assertEqual(self.client.get('/api/pedidos/').status_code, 200)


class PrefijoSkuTest(TestCase):
    def test_usa_el_prefijo_de_la_categoria(self):
        frenos = Categoria.objects.create(nombre='Sistema de Frenos', prefijo_sku='FRE')
        r = Repuesto.objects.create(categoria=frenos, nombre='a', precio_unitario=1)
        self.assertEqual(r.sku, 'RS-FRE-0001')

    def test_desarmaduria_usa_des_sin_rs(self):
        des = Categoria.objects.create(nombre='Desarmaduría', prefijo_sku='DES')
        Repuesto.objects.create(categoria=des, sku='DES-CAJ-161', nombre='a', precio_unitario=1)  # formato antiguo
        Repuesto.objects.create(categoria=des, sku='DES-0003', nombre='b', precio_unitario=1)
        r = Repuesto.objects.create(categoria=des, nombre='c', precio_unitario=1)
        self.assertEqual(r.sku, 'DES-0004')

    def test_prefijo_editable_por_api(self):
        cat = Categoria.objects.create(nombre='Suspensión')
        self.client.force_login(User.objects.create_user('admin', 'a@a.cl', 'x', is_staff=True))
        url = f'/api/categorias/{cat.id}/'
        self.assertEqual(self.client.patch(url, {'prefijo_sku': 'sus'}, content_type='application/json').json()['prefijo_sku'], 'SUS')
        self.assertEqual(self.client.patch(url, {'prefijo_sku': 'S1'}, content_type='application/json').status_code, 400)


class CargaMasivaDuplicadosTest(CargaMasivaTest):
    def test_marca_duplicadas_y_no_las_importa(self):
        Repuesto.objects.create(categoria=Categoria.objects.get(nombre='Filtros'), sku='RS-FIL-0009',
                                nombre='Filtro X', marca_fabricante='Bosch', codigo_oem='OEM9', precio_unitario=1)
        self.client.force_login(self.admin)
        filas = (
            'FILTRO X;bosch;Filtros;Filtro de Aceite;NUEVO;1000;1;OEM9;;;;\n'   # ya existe en la base
            'Filtro Y;Bosch;Filtros;Filtro de Aceite;NUEVO;1000;1;OEM8;;;;\n'
            'Filtro Y;Bosch;Filtros;Filtro de Aceite;NUEVO;1000;1;OEM8;;;;\n'   # repetida en el archivo
        )
        r = self.enviar(filas, 'importar').json()
        self.assertEqual([f['estado'] for f in r['filas']], ['duplicada', 'ok', 'duplicada'])
        self.assertEqual((r['duplicadas'], r['creadas']), (2, 1))
        self.assertEqual(Repuesto.objects.filter(nombre__iexact='filtro x').count(), 1)


from datetime import timedelta

from django.utils import timezone

from .models import DetallePedido, SolicitudEspecial, Usuario


def _admin(nombre='admin'):
    return User.objects.create_user(nombre, f'{nombre}@a.cl', 'x', is_staff=True)


class CatalogoAdminTest(TestCase):
    def setUp(self):
        self.filtros = Categoria.objects.create(nombre='Filtros')
        self.frenos = Categoria.objects.create(nombre='Frenos')
        for i in range(25):
            Repuesto.objects.create(categoria=self.filtros, nombre=f'Filtro {i}', precio_unitario=1000, stock_disponible=10)
        Repuesto.objects.create(categoria=self.frenos, nombre='Pastilla', codigo_oem='OEM-777',
                                precio_unitario=1, stock_disponible=2, condicion='USADO')

    def test_sin_page_sigue_devolviendo_un_arreglo(self):
        data = self.client.get('/api/repuestos/').json()
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 26)

    def test_paginado_con_page(self):
        data = self.client.get('/api/repuestos/?page=2').json()
        self.assertEqual(data['count'], 26)
        self.assertEqual(len(data['results']), 6)
        self.assertEqual(len(self.client.get('/api/repuestos/?page=1&page_size=5').json()['results']), 5)

    def test_busqueda_y_filtros(self):
        def nombres(qs):
            return [r['nombre'] for r in self.client.get(f'/api/repuestos/?page=1&{qs}').json()['results']]
        self.assertEqual(nombres('q=oem-777'), ['Pastilla'])
        self.assertEqual(nombres('q=RS-FRE'), ['Pastilla'])
        self.assertEqual(nombres(f'categoria={self.frenos.id}'), ['Pastilla'])
        self.assertEqual(nombres('condicion=usado'), ['Pastilla'])
        self.assertEqual(nombres('stock_critico=1'), ['Pastilla'])
        self.assertEqual(self.client.get('/api/repuestos/?page=1&q=filtro').json()['count'], 25)

    def test_eliminar_repuesto_vendido_responde_400(self):
        rep = Repuesto.objects.get(nombre='Pastilla')
        pedido = Pedido.objects.create(direccion_calle='x', subtotal=1, costo_envio=0, monto_total=1, estado='PAGADO')
        DetallePedido.objects.create(pedido=pedido, repuesto=rep, cantidad=1, precio_historico=1)
        self.client.force_login(_admin())
        r = self.client.delete(f'/api/repuestos/{rep.id}/')
        self.assertEqual(r.status_code, 400)
        self.assertIn('Desactívalo', r.json()['error'])
        r = self.client.patch(f'/api/repuestos/{rep.id}/', {'activo': False}, content_type='application/json')
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Repuesto.objects.get(id=rep.id).activo)


class VehiculoAdminTest(TestCase):
    def test_crear_editar_y_validar_anios(self):
        datos = {'marca': 'Toyota', 'modelo': 'Yaris', 'anio_inicio': 2010, 'anio_fin': 2015}
        self.assertEqual(self.client.post('/api/vehiculos/', datos, content_type='application/json').status_code, 403)
        self.client.force_login(_admin())
        v = self.client.post('/api/vehiculos/', datos, content_type='application/json').json()
        url = f"/api/vehiculos/{v['id']}/"
        r = self.client.patch(url, {'motorizacion': '1.5'}, content_type='application/json')
        self.assertEqual(r.json()['nombre'], 'Toyota Yaris 2010-2015 (Motor 1.5)')
        r = self.client.patch(url, {'anio_fin': 2005}, content_type='application/json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('anio_fin', r.json())


class ResumenAdminTest(TestCase):
    URL = '/api/admin/resumen/'

    def pedido(self, monto, estado='PAGADO', hace_dias=0):
        p = Pedido.objects.create(direccion_calle='x', subtotal=monto, costo_envio=0, monto_total=monto, estado=estado)
        # fecha_creacion es auto_now_add: se ajusta después de crear
        Pedido.objects.filter(id=p.id).update(fecha_creacion=timezone.now() - timedelta(days=hace_dias))
        return p

    def setUp(self):
        cat = Categoria.objects.create(nombre='Filtros')
        a = Repuesto.objects.create(categoria=cat, nombre='A', precio_unitario=1000, stock_disponible=3)
        b = Repuesto.objects.create(categoria=cat, nombre='B', precio_unitario=500, stock_disponible=0)
        Repuesto.objects.create(categoria=cat, nombre='C', precio_unitario=1, stock_disponible=0, activo=False)
        Repuesto.objects.create(categoria=cat, nombre='D', precio_unitario=1, stock_disponible=50)
        DetallePedido.objects.create(pedido=self.pedido(3000), repuesto=a, cantidad=3, precio_historico=1000)
        DetallePedido.objects.create(pedido=self.pedido(1000, hace_dias=3), repuesto=b, cantidad=2, precio_historico=500)
        DetallePedido.objects.create(pedido=self.pedido(9000, hace_dias=60), repuesto=b, cantidad=10, precio_historico=900)
        self.pedido(5000, estado='PENDIENTE_PAGO')
        self.pedido(7000, estado='RECHAZADO', hace_dias=1)
        u = Usuario.objects.create(rut='1-9', nombre_completo='x', email='x@x.cl', password_hash='x', rol='cliente')
        for estado in ['PENDIENTE', 'EN_GESTION', 'COTIZADA', 'RESUELTA', 'NO_DISPONIBLE']:
            SolicitudEspecial.objects.create(usuario=u, vin_vehiculo='x', pieza_requerida='x', nivel_urgencia='x', estado=estado)

    def test_solo_administradores(self):
        self.assertEqual(self.client.get(self.URL).status_code, 403)
        self.client.force_login(User.objects.create_user('cliente', 'c@c.cl', 'x'))
        self.assertEqual(self.client.get(self.URL).status_code, 403)

    def test_periodo_invalido(self):
        self.client.force_login(_admin())
        self.assertEqual(self.client.get(self.URL + '?periodo=90d').status_code, 400)

    def test_indicadores_7d(self):
        self.client.force_login(_admin())
        r = self.client.get(self.URL + '?periodo=7d').json()
        self.assertEqual(r['ventas_totales'], 4000)  # el pedido de hace 60 días queda fuera
        self.assertEqual(r['ticket_promedio'], 2000)
        self.assertEqual(r['pedidos_por_estado'], {'PAGADO': 2, 'PENDIENTE_PAGO': 1, 'RECHAZADO': 1})
        self.assertEqual(len(r['ventas_por_dia']), 7)
        self.assertEqual(sum(d['total'] for d in r['ventas_por_dia']), 4000)
        self.assertEqual(r['ventas_por_dia'][-1]['fecha'], r['hasta'])
        self.assertEqual([m['nombre'] for m in r['mas_vendidos']], ['A', 'B'])
        self.assertEqual(r['mas_vendidos'][0]['total'], 3000)
        self.assertEqual([i['nombre'] for i in r['stock_critico']['items']], ['A'])
        self.assertEqual(r['agotados']['cantidad'], 1)  # C está inactivo
        self.assertEqual(r['solicitudes_pendientes'], 1)

    def test_pedidos_por_revisar_no_suman_a_las_ventas(self):
        self.pedido(8000, estado='REVISAR_STOCK')
        self.pedido(6000, estado='REVISAR_STOCK', hace_dias=90)  # fuera del período, igual está pendiente
        self.client.force_login(_admin())
        r = self.client.get(self.URL + '?periodo=7d').json()
        self.assertEqual(r['pedidos_por_revisar'], 2)
        self.assertEqual(r['ventas_totales'], 4000)
        self.assertEqual(r['ticket_promedio'], 2000)
        self.assertEqual(r['pedidos_por_estado']['REVISAR_STOCK'], 1)

    def test_hoy_y_todo(self):
        self.client.force_login(_admin())
        self.assertEqual(len(self.client.get(self.URL + '?periodo=hoy').json()['ventas_por_dia']), 1)
        todo = self.client.get(self.URL + '?periodo=todo').json()
        self.assertEqual(todo['ventas_totales'], 13000)
        self.assertEqual(todo['mas_vendidos'][0]['nombre'], 'B')
        self.assertGreaterEqual(len(todo['ventas_por_dia']), 60)

    def test_pedidos_en_curso_siguen_contando_como_venta(self):
        for estado in ['EN_PREPARACION', 'DESPACHADO', 'ENTREGADO']:
            self.pedido(1000, estado=estado)
        self.client.force_login(_admin())
        self.assertEqual(self.client.get(self.URL + '?periodo=7d').json()['ventas_totales'], 7000)


from . import views
from .models import TarifaDespacho, TransaccionPago


def _pedido(email='ana@cliente.cl', estado='PAGADO', monto=10000, nombre='Ana', hace_dias=0):
    p = Pedido.objects.create(direccion_calle='Calle 1', subtotal=monto, costo_envio=0, monto_total=monto,
                              estado=estado, email_cliente=email, nombre_cliente=nombre, rut_cliente='11111111-1')
    if hace_dias:
        Pedido.objects.filter(id=p.id).update(fecha_creacion=timezone.now() - timedelta(days=hace_dias))
    return p


class PermisosPanelTest(TestCase):
    """Datos de clientes, pedidos y solicitudes: solo para is_staff."""
    def test_rechaza_anonimos_y_clientes(self):
        p = _pedido()
        u = Usuario.objects.create(rut='1-9', nombre_completo='x', email='x@x.cl', password_hash='x', rol='cliente')
        s = SolicitudEspecial.objects.create(usuario=u, vin_vehiculo='x', pieza_requerida='x', nivel_urgencia='x', estado='PENDIENTE')
        urls = ['/api/pedidos/', f'/api/pedidos/{p.id}/', '/api/admin/solicitudes/', f'/api/admin/solicitudes/{s.id}/',
                '/api/admin/clientes/', '/api/admin/clientes/detalle/?email=ana@cliente.cl']
        for usuario in [None, User.objects.create_user('cliente', 'c@c.cl', 'x')]:
            if usuario:
                self.client.force_login(usuario)
            for url in urls:
                self.assertEqual(self.client.get(url).status_code, 403, url)
            r = self.client.post(f'/api/pedidos/{p.id}/avanzar-estado/', {'estado': 'EN_PREPARACION'}, content_type='application/json')
            self.assertEqual(r.status_code, 403)
            r = self.client.patch(f'/api/admin/solicitudes/{s.id}/', {'estado': 'RESUELTA'}, content_type='application/json')
            self.assertEqual(r.status_code, 403)
        self.assertEqual(Pedido.objects.get(id=p.id).estado, 'PAGADO')
        self.client.force_login(_admin())
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_pedidos_no_se_editan_directamente(self):
        p = _pedido()
        self.client.force_login(_admin())
        r = self.client.patch(f'/api/pedidos/{p.id}/', {'estado': 'ENTREGADO'}, content_type='application/json')
        self.assertEqual(r.status_code, 405)
        self.assertEqual(self.client.delete(f'/api/pedidos/{p.id}/').status_code, 405)


class PedidosAdminTest(TestCase):
    def setUp(self):
        self.client.force_login(_admin())

    def avanzar(self, pedido, estado, **extra):
        return self.client.post(f'/api/pedidos/{pedido.id}/avanzar-estado/', {'estado': estado, **extra},
                                content_type='application/json')

    def test_avance_completo_y_datos_de_despacho(self):
        p = _pedido()
        self.assertEqual(self.avanzar(p, 'EN_PREPARACION').json()['estado'], 'EN_PREPARACION')
        r = self.avanzar(p, 'DESPACHADO')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(set(r.json()), {'empresa_courier', 'codigo_seguimiento'})
        r = self.avanzar(p, 'DESPACHADO', empresa_courier='Starken', codigo_seguimiento='ABC123')
        self.assertEqual((r.json()['estado'], r.json()['empresa_courier']), ('DESPACHADO', 'Starken'))
        r = self.avanzar(p, 'ENTREGADO').json()
        self.assertEqual((r['estado'], r['siguiente_estado']), ('ENTREGADO', None))

    def test_no_salta_ni_retrocede(self):
        p = _pedido()
        self.assertEqual(self.avanzar(p, 'DESPACHADO', empresa_courier='x', codigo_seguimiento='y').status_code, 400)
        self.assertEqual(self.avanzar(p, 'ENTREGADO').status_code, 400)
        self.assertEqual(self.avanzar(p, 'ESTADO_INVENTADO').status_code, 400)
        self.avanzar(p, 'EN_PREPARACION')
        self.assertEqual(self.avanzar(p, 'PAGADO').status_code, 400)
        self.assertEqual(self.avanzar(p, 'EN_PREPARACION').status_code, 400)
        self.assertEqual(Pedido.objects.get(id=p.id).estado, 'EN_PREPARACION')

    def test_estados_sin_pago_o_finales_no_avanzan(self):
        for estado in ['PENDIENTE_PAGO', 'RECHAZADO', 'ANULADO', 'ENTREGADO']:
            r = self.avanzar(_pedido(estado=estado), 'EN_PREPARACION')
            self.assertEqual(r.status_code, 400, estado)

    def test_revisar_stock_pasa_a_preparacion(self):
        p = _pedido(estado='REVISAR_STOCK')
        self.assertEqual(self.avanzar(p, 'EN_PREPARACION').status_code, 200)

    def test_conflicto_si_otro_lo_cambio_antes(self):
        p = _pedido()
        from unittest import mock
        # Simula que otro administrador avanzó el pedido entre la lectura y la escritura
        original = views.PedidoViewSet.get_object
        def leer_y_cambiar(vista):
            obj = original(vista)
            Pedido.objects.filter(id=obj.id).update(estado='EN_PREPARACION')
            return obj
        with mock.patch.object(views.PedidoViewSet, 'get_object', leer_y_cambiar):
            self.assertEqual(self.avanzar(p, 'EN_PREPARACION').status_code, 409)

    def test_filtros_y_detalle(self):
        tarifa = TarifaDespacho.objects.create(region='RM', comuna='Ñuñoa', costo_base_kg=1000, dias_habiles_estimados=2)
        cat = Categoria.objects.create(nombre='Filtros')
        rep = Repuesto.objects.create(categoria=cat, nombre='Filtro', precio_unitario=5000)
        p = _pedido(email='pedro@x.cl', nombre='Pedro', monto=10000)
        Pedido.objects.filter(id=p.id).update(tarifa=tarifa)
        DetallePedido.objects.create(pedido=p, repuesto=rep, cantidad=2, precio_historico=5000)
        TransaccionPago.objects.create(pedido=p, token_pasarela='tok', monto_pagado=10000, estado_pago='APROBADO')
        _pedido(estado='RECHAZADO')
        _pedido(hace_dias=10)

        def ids(qs):
            return [x['id'] for x in self.client.get(f'/api/pedidos/?page=1&{qs}').json()['results']]
        self.assertEqual(ids('q=pedro'), [p.id])
        self.assertEqual(ids('q=PEDRO@X'), [p.id])
        self.assertEqual(len(ids('estado=PAGADO')), 2)
        hoy = timezone.localdate(timezone=views.ZONA_CHILE).isoformat()
        self.assertEqual(len(ids(f'desde={hoy}&hasta={hoy}')), 2)
        self.assertEqual(self.client.get('/api/pedidos/?desde=24-11-2026').status_code, 400)

        d = self.client.get(f'/api/pedidos/{p.id}/').json()
        self.assertEqual(d['productos'][0]['subtotal'], 10000)
        self.assertEqual((d['comuna'], d['pagos'][0]['estado_pago']), ('Ñuñoa', 'APROBADO'))
        self.assertNotIn('token_pasarela', d['pagos'][0])
        self.assertEqual(d['siguiente_estado'], 'EN_PREPARACION')


class SolicitudesAdminTest(TestCase):
    def setUp(self):
        u = Usuario.objects.create(rut='1-9', nombre_completo='Juan Pérez', email='juan@x.cl', password_hash='x', rol='cliente')
        self.s = SolicitudEspecial.objects.create(usuario=u, vin_vehiculo='VIN1', pieza_requerida='Foco trasero',
                                                  nivel_urgencia='ALTA', estado='PENDIENTE')
        self.client.force_login(_admin())
        self.url = f'/api/admin/solicitudes/{self.s.id}/'

    def test_lista_detalle_y_cambio_de_estado(self):
        data = self.client.get('/api/admin/solicitudes/?page=1&q=foco').json()
        self.assertEqual(data['results'][0]['cliente_nombre'], 'Juan Pérez')
        self.assertEqual(self.client.get('/api/admin/solicitudes/?page=1&estado=RESUELTA').json()['count'], 0)
        r = self.client.patch(self.url, {'estado': 'EN_GESTION', 'valor_cotizado': 45000, 'comentario_admin': 'Llega el martes',
                                         'pieza_requerida': 'otra cosa'}, content_type='application/json')
        self.assertEqual((r.json()['estado_nombre'], r.json()['valor_cotizado']), ('En gestión', 45000))
        self.assertEqual(r.json()['pieza_requerida'], 'Foco trasero')  # lo escrito por el cliente no cambia

    def test_valida_estado_y_valor(self):
        self.assertEqual(self.client.patch(self.url, {'estado': 'CERRADA'}, content_type='application/json').status_code, 400)
        self.assertEqual(self.client.patch(self.url, {'valor_cotizado': -1}, content_type='application/json').status_code, 400)
        self.assertEqual(self.client.put(self.url, {'estado': 'RESUELTA'}, content_type='application/json').status_code, 405)
        self.assertEqual(self.client.delete(self.url).status_code, 405)


class ClientesAdminTest(TestCase):
    def setUp(self):
        _pedido('ana@cliente.cl', monto=10000, hace_dias=5, nombre='Ana')
        _pedido('ana@cliente.cl', estado='DESPACHADO', monto=5000, hace_dias=1, nombre='Ana María')
        _pedido('ana@cliente.cl', estado='RECHAZADO', monto=99000)
        _pedido('beto@cliente.cl', estado='PENDIENTE_PAGO', monto=3000, nombre='Beto')
        self.client.force_login(_admin())

    def test_lista_agrupada_por_correo(self):
        clientes = self.client.get('/api/admin/clientes/').json()
        self.assertEqual([c['email_cliente'] for c in clientes], ['ana@cliente.cl', 'beto@cliente.cl'])
        ana, beto = clientes
        self.assertEqual((ana['pedidos'], ana['pedidos_pagados'], ana['total_gastado'], ana['nombre']), (3, 2, 15000, 'Ana'))
        self.assertEqual((beto['total_gastado'], beto['ultima_compra']), (0, None))
        self.assertEqual(self.client.get('/api/admin/clientes/?page=1&q=beto').json()['count'], 1)

    def test_detalle_con_historial(self):
        r = self.client.get('/api/admin/clientes/detalle/?email=ANA@cliente.cl').json()
        self.assertEqual((r['total_gastado'], len(r['pedidos']), r['rut']), (15000, 3, '11111111-1'))
        self.assertEqual(self.client.get('/api/admin/clientes/detalle/?email=nadie@x.cl').status_code, 404)


from smtplib import SMTPException
from unittest import mock

from django.core import mail
from django.test import TransactionTestCase


class CorreoSolicitudTest(TransactionTestCase):
    """Sin la transacción envolvente de TestCase, para que on_commit corra al guardar como en producción."""
    def setUp(self):
        u = Usuario.objects.create(rut='1-9', nombre_completo='Juan Pérez', email='juan@x.cl', password_hash='x', rol='cliente')
        self.s = SolicitudEspecial.objects.create(usuario=u, vin_vehiculo='VIN1', pieza_requerida='Foco trasero',
                                                  nivel_urgencia='ALTA', estado='PENDIENTE')
        self.url = f'/api/admin/solicitudes/{self.s.id}/'
        self.client.force_login(_admin())

    def patch(self, **datos):
        return self.client.patch(self.url, datos, content_type='application/json')

    def test_envia_correo_sin_comentario_interno(self):
        r = self.patch(estado='COTIZADA', valor_cotizado=45000, comentario_admin='Proveedor X cobra 30000',
                       notificar_cliente=True, mensaje_cliente='  Llega el martes <b>sin falta</b>  ')
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.json()['correo_enviado'], r.json()['correo_destino']), (True, 'juan@x.cl'))
        self.assertEqual(len(mail.outbox), 1)
        m = mail.outbox[0]
        self.assertEqual(m.to, ['juan@x.cl'])
        self.assertEqual(m.subject, f'Tu solicitud #{self.s.id} en RepuestosRS: Cotizada')
        for texto in ['Foco trasero', 'Estado: Cotizada', '$45.000', 'Llega el martes <b>sin falta</b>']:
            self.assertIn(texto, m.body)
        self.assertNotIn('Proveedor X', m.body)
        self.assertEqual(m.alternatives, [])  # solo texto plano
        self.s.refresh_from_db()
        self.assertEqual(self.s.ultimo_mensaje_cliente, 'Llega el martes <b>sin falta</b>')
        self.assertIsNotNone(self.s.fecha_ultimo_correo)
        self.assertEqual(r.json()['ultimo_mensaje_cliente'], self.s.ultimo_mensaje_cliente)

    def test_no_envia_si_no_se_pide(self):
        r = self.patch(estado='NO_DISPONIBLE', mensaje_cliente='no debería salir')
        self.assertEqual(r.status_code, 200)
        self.assertNotIn('correo_enviado', r.json())
        self.assertEqual(len(mail.outbox), 0)
        self.s.refresh_from_db()
        self.assertEqual((self.s.estado, self.s.fecha_ultimo_correo, self.s.ultimo_mensaje_cliente), ('NO_DISPONIBLE', None, ''))

    def test_si_falla_el_envio_el_cambio_se_guarda(self):
        with mock.patch('catalog.views.send_mail', side_effect=SMTPException('caído')), \
                self.assertLogs('catalog.views', 'ERROR'):
            r = self.patch(estado='RESUELTA', notificar_cliente=True, mensaje_cliente='Hola')
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()['correo_enviado'])
        self.assertIn('SMTPException', r.json()['motivo_correo'])
        self.s.refresh_from_db()
        self.assertEqual((self.s.estado, self.s.fecha_ultimo_correo), ('RESUELTA', None))

    def test_valida_largo_del_mensaje(self):
        r = self.patch(estado='RESUELTA', notificar_cliente=True, mensaje_cliente='x' * 1001)
        self.assertEqual(r.status_code, 400)
        self.assertIn('mensaje_cliente', r.json())
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(SolicitudEspecial.objects.get(id=self.s.id).estado, 'PENDIENTE')

    def test_solo_administradores_pueden_notificar(self):
        self.client.logout()
        for usuario in [None, User.objects.create_user('cliente', 'c@c.cl', 'x')]:
            if usuario:
                self.client.force_login(usuario)
            r = self.patch(estado='RESUELTA', notificar_cliente=True, mensaje_cliente='Hola')
            self.assertEqual(r.status_code, 403)
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(SolicitudEspecial.objects.get(id=self.s.id).estado, 'PENDIENTE')


# --- Tarea D: seguridad para despliegue ---

import os
import subprocess
import sys
from pathlib import Path

from django.test import override_settings

from .models import Vehiculo


class PermisosEndpointsTest(TestCase):
    """Recorre la API como anónimo, cliente y admin."""

    def setUp(self):
        self.cat = Categoria.objects.create(nombre='Filtros')
        self.sub = Subcategoria.objects.create(categoria=self.cat, nombre='Aceite')
        self.rep = Repuesto.objects.create(categoria=self.cat, nombre='Filtro', precio_unitario=5000, stock_disponible=5)
        self.veh = Vehiculo.objects.create(marca='Toyota', modelo='Hilux')
        self.tarifa = TarifaDespacho.objects.create(region='RM', comuna='Santiago', costo_base_kg=3000, dias_habiles_estimados=2)
        self.pedido = _pedido()
        u = Usuario.objects.create(rut='12345678-5', nombre_completo='Ana', email='ana@cliente.cl', password_hash='x', rol='CLIENTE')
        self.sol = SolicitudEspecial.objects.create(usuario=u, vin_vehiculo='x', pieza_requerida='x', nivel_urgencia='x', estado='PENDIENTE')
        self.cliente = User.objects.create_user('cli@c.cl', 'cli@c.cl', 'x')

    def rutas_admin(self):
        return [
            ('get', '/api/admin/resumen/'), ('get', '/api/admin/clientes/'),
            ('get', '/api/admin/clientes/detalle/?email=ana@cliente.cl'),
            ('get', '/api/admin/solicitudes/'), ('get', f'/api/admin/solicitudes/{self.sol.id}/'),
            ('patch', f'/api/admin/solicitudes/{self.sol.id}/'),
            ('get', '/api/pedidos/'), ('get', f'/api/pedidos/{self.pedido.id}/'),
            ('post', f'/api/pedidos/{self.pedido.id}/avanzar-estado/'),
            ('post', '/api/repuestos/carga-masiva/'),
        ]

    def escrituras_catalogo(self):
        rutas = []
        for base, obj in [('repuestos', self.rep), ('categorias', self.cat), ('subcategorias', self.sub), ('vehiculos', self.veh)]:
            rutas += [('post', f'/api/{base}/'), ('put', f'/api/{base}/{obj.id}/'),
                      ('patch', f'/api/{base}/{obj.id}/'), ('delete', f'/api/{base}/{obj.id}/')]
        return rutas

    def llamar(self, metodo, url):
        return getattr(self.client, metodo)(url, {}, content_type='application/json')

    def test_anonimo_y_cliente_no_entran_a_admin_ni_escriben_catalogo(self):
        for usuario in [None, self.cliente]:
            if usuario:
                self.client.force_login(usuario)
            for metodo, url in self.rutas_admin() + self.escrituras_catalogo():
                self.assertEqual(self.llamar(metodo, url).status_code, 403, f'{usuario} {metodo} {url}')
        # Nada cambió
        self.assertTrue(Repuesto.objects.filter(id=self.rep.id, nombre='Filtro').exists())
        self.assertEqual(Pedido.objects.get(id=self.pedido.id).estado, 'PAGADO')

    def test_admin_entra_al_panel(self):
        self.client.force_login(_admin())
        for metodo, url in self.rutas_admin():
            if metodo == 'get':
                self.assertEqual(self.client.get(url).status_code, 200, url)
        r = self.client.patch(f'/api/repuestos/{self.rep.id}/', {'stock_disponible': 9}, content_type='application/json')
        self.assertEqual(r.status_code, 200)

    def test_lo_publico_responde_a_anonimos(self):
        publicas = [
            '/api/categorias/', f'/api/categorias/{self.cat.id}/',
            '/api/subcategorias/', f'/api/subcategorias/{self.sub.id}/',
            '/api/repuestos/', f'/api/repuestos/{self.rep.id}/',
            '/api/vehiculos/', f'/api/vehiculos/{self.veh.id}/',
            '/api/tarifas-despacho/', '/api/buscar-vehiculo/?q=ABCD12',
        ]
        for url in publicas:
            self.assertEqual(self.client.get(url).status_code, 200, url)
        # Compra como invitado: la cotización no exige sesión
        r = self.client.post('/api/checkout/', {'items': [{'id': self.rep.id, 'cantidad': 1}], 'tarifa_id': self.tarifa.id,
                                                'simular': True}, content_type='application/json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['subtotal'], 5000)
        # El retorno de Webpay es público (redirige al sitio, no responde 403)
        self.assertEqual(self.client.get('/api/webpay/retorno/').status_code, 302)
        self.assertEqual(self.client.post('/api/logout/').status_code, 200)

    def test_rutas_de_usuario_piden_sesion(self):
        for metodo, url in [('get', '/api/mi-perfil/'), ('post', '/api/solicitudes/')]:
            r = self.llamar(metodo, url)
            self.assertEqual(r.status_code, 403, url)
            self.assertIn('iniciar sesión', r.json()['error'])

    def test_register_ignora_rol_e_is_staff(self):
        r = self.client.post('/api/register/', {
            'rut': '11111111-1', 'nombre_completo': 'Eva Mala', 'email': 'eva@x.cl', 'password': 'ClaveSegura123',
            'rol': 'ADMIN', 'is_staff': True, 'is_superuser': True,
        }, content_type='application/json')
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()['rol'], 'CLIENTE')
        self.assertEqual(Usuario.objects.get(email='eva@x.cl').rol, 'CLIENTE')
        user = User.objects.get(email='eva@x.cl')
        self.assertFalse(user.is_staff or user.is_superuser)
        self.client.force_login(user)
        self.assertEqual(self.client.get('/api/admin/resumen/').status_code, 403)

    def test_login_mismo_mensaje_si_no_existe_o_clave_mala(self):
        User.objects.create_user('ana@x.cl', 'ana@x.cl', 'buena')
        login = lambda email, clave: self.client.post('/api/login/', {'email': email, 'password': clave}, content_type='application/json')
        no_existe, mala = login('nadie@x.cl', 'buena'), login('ana@x.cl', 'mala')
        self.assertEqual((no_existe.status_code, mala.status_code), (401, 401))
        self.assertEqual(no_existe.json(), mala.json())
        self.assertEqual(mala.json()['error'], 'Correo o contraseña incorrectos')
        self.assertEqual(login('ana@x.cl', 'buena').status_code, 200)

    @override_settings(WEBPAY_COMMERCE_CODE='', WEBPAY_API_KEY='')
    def test_webpay_sin_credenciales_falla_con_error_claro(self):
        cliente = {'email': 'a@a.cl', 'nombre': 'Ana', 'apellido': 'Pérez', 'rut': '11111111-1',
                   'telefono': '12345678', 'direccion': 'Calle 123'}
        antes = Pedido.objects.count()
        with mock.patch.object(views.requests, 'post') as post:
            r = self.client.post('/api/checkout/', {'items': [{'id': self.rep.id, 'cantidad': 1}], 'tarifa_id': self.tarifa.id,
                                                    'cliente': cliente}, content_type='application/json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('Webpay no está configurado', r.json()['error'])
        post.assert_not_called()
        self.assertEqual(Pedido.objects.count(), antes)  # el pedido se deshace


class SettingsProduccionTest(TestCase):
    """Carga config/settings.py en un proceso aparte con distintas variables de entorno."""
    BASE = Path(__file__).resolve().parent.parent

    def cargar(self, **env):
        # Valores vacíos explícitos: el .env local no los pisa (solo rellena las que faltan)
        entorno = {**os.environ, 'DJANGO_SECRET_KEY': '', 'WEBPAY_COMMERCE_CODE': '', 'WEBPAY_API_KEY': '',
                   'DJANGO_ALLOWED_HOSTS': '', 'DJANGO_CSRF_TRUSTED_ORIGINS': '', **env}
        codigo = ('import config.settings as s; print(s.DEBUG, getattr(s, "SESSION_COOKIE_SECURE", False), '
                  'getattr(s, "CSRF_COOKIE_SECURE", False), bool(s.WEBPAY_API_KEY), s.ALLOWED_HOSTS, s.CSRF_TRUSTED_ORIGINS)')
        return subprocess.run([sys.executable, '-c', codigo], cwd=self.BASE, env=entorno, capture_output=True, text=True)

    def test_sin_secret_key_en_produccion_no_arranca(self):
        r = self.cargar(DJANGO_DEBUG='False')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('DJANGO_SECRET_KEY', r.stderr)

    def test_produccion_cookies_seguras_y_sin_credenciales_de_integracion(self):
        r = self.cargar(DJANGO_DEBUG='False', DJANGO_SECRET_KEY='k' * 50, DJANGO_ALLOWED_HOSTS='api.x.cl',
                        DJANGO_CSRF_TRUSTED_ORIGINS='https://x.cl')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "False True True False ['api.x.cl'] ['https://x.cl']")

    def test_desarrollo_funciona_sin_variables(self):
        r = self.cargar(DJANGO_DEBUG='True')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(),
                         "True False False True ['localhost', '127.0.0.1'] ['http://localhost:4200']")


# --- Cuenta del cliente: perfil, contraseña, eliminación, vehículos y pedidos ---

from .models import VehiculoCliente


class CuentaClienteTest(TestCase):
    CLAVE = 'ClaveSegura123'

    def crear_cliente(self, email, rut, nombre='Ana Pérez'):
        usuario = Usuario.objects.create(rut=rut, nombre_completo=nombre, email=email, password_hash='x',
                                         telefono='+56911112222', rol='CLIENTE')
        user = User.objects.create_user(email, email, self.CLAVE, first_name=nombre.split()[0])
        return usuario, user

    def setUp(self):
        self.ana, self.user_ana = self.crear_cliente('ana@x.cl', '11111111-1')
        self.beto, self.user_beto = self.crear_cliente('beto@x.cl', '22222222-2', 'Beto Soto')
        self.veh = Vehiculo.objects.create(marca='Toyota', modelo='Yaris', anio_inicio=2015, anio_fin=2020)
        self.veh_ana = VehiculoCliente.objects.create(usuario=self.ana, vehiculo_base=self.veh, patente='AAAA11')
        self.veh_beto = VehiculoCliente.objects.create(usuario=self.beto, vehiculo_base=self.veh, patente='BBBB22')
        self.cat = Categoria.objects.create(nombre='Filtros')
        self.rep = Repuesto.objects.create(categoria=self.cat, nombre='Filtro aceite', precio_unitario=5000, stock_disponible=5)
        self.pedido_ana = _pedido(email='ana@x.cl', estado='DESPACHADO', hace_dias=2)
        Pedido.objects.filter(id=self.pedido_ana.id).update(usuario=self.ana, empresa_courier='Starken',
                                                            codigo_seguimiento='ABC 123', subtotal=10000, costo_envio=3000,
                                                            monto_total=13000)
        DetallePedido.objects.create(pedido=self.pedido_ana, repuesto=self.rep, cantidad=2, precio_historico=5000)
        self.invitado_ana = _pedido(email='ANA@x.cl')  # compra como invitada con su mismo correo
        self.pedido_beto = _pedido(email='beto@x.cl')
        Pedido.objects.filter(id=self.pedido_beto.id).update(usuario=self.beto)

    def json(self, metodo, url, data=None):
        return getattr(self.client, metodo)(url, data or {}, content_type='application/json')

    def test_anonimo_recibe_403(self):
        rutas = [('get', '/api/mi-perfil/'), ('patch', '/api/mi-perfil/'), ('post', '/api/mi-perfil/cambiar-password/'),
                 ('post', '/api/mi-perfil/eliminar-cuenta/'), ('get', '/api/mis-vehiculos/'),
                 ('delete', f'/api/mis-vehiculos/{self.veh_ana.id}/'), ('get', '/api/mis-pedidos/'),
                 ('get', f'/api/mis-pedidos/{self.pedido_ana.id}/')]
        for metodo, url in rutas:
            self.assertEqual(self.json(metodo, url).status_code, 403, f'{metodo} {url}')
        self.assertTrue(VehiculoCliente.objects.filter(id=self.veh_ana.id).exists())

    def test_cliente_no_ve_lo_de_otro(self):
        self.client.force_login(self.user_ana)
        ids = [p['id'] for p in self.client.get('/api/mis-pedidos/').json()]
        self.assertEqual(sorted(ids), sorted([self.pedido_ana.id, self.invitado_ana.id]))
        self.assertEqual(self.client.get(f'/api/mis-pedidos/{self.pedido_beto.id}/').status_code, 404)
        self.assertEqual([v['patente'] for v in self.client.get('/api/mis-vehiculos/').json()], ['AAAA11'])
        self.assertEqual(self.client.delete(f'/api/mis-vehiculos/{self.veh_beto.id}/').status_code, 404)
        self.assertTrue(VehiculoCliente.objects.filter(id=self.veh_beto.id).exists())
        self.assertEqual(self.client.delete(f'/api/mis-vehiculos/{self.veh_ana.id}/').status_code, 204)
        self.assertFalse(VehiculoCliente.objects.filter(id=self.veh_ana.id).exists())

    def test_lista_y_detalle_de_pedidos(self):
        self.client.force_login(self.user_ana)
        lista = self.client.get('/api/mis-pedidos/').json()
        self.assertEqual(lista[0]['id'], self.invitado_ana.id)  # más reciente primero
        despachado = next(p for p in lista if p['id'] == self.pedido_ana.id)
        self.assertEqual((despachado['monto_total'], despachado['cantidad_items'], despachado['estado']), (13000, 2, 'DESPACHADO'))
        d = self.client.get(f'/api/mis-pedidos/{self.pedido_ana.id}/').json()
        self.assertEqual(d['productos'], [{'nombre': 'Filtro aceite', 'sku': self.rep.sku, 'cantidad': 2,
                                           'precio': 5000, 'subtotal': 10000}])
        self.assertEqual((d['subtotal'], d['costo_envio'], d['monto_total']), (10000, 3000, 13000))
        for privado in ('pagos', 'rut_cliente', 'telefono_cliente', 'email_cliente'):
            self.assertNotIn(privado, d)

    @override_settings(COURIER_TRACKING_URLS={'starken': 'https://x.cl/seguir?c={codigo}'})
    def test_seguimiento_url(self):
        self.client.force_login(self.user_ana)
        url = f'/api/mis-pedidos/{self.pedido_ana.id}/'
        self.assertEqual(self.client.get(url).json()['seguimiento_url'], 'https://x.cl/seguir?c=ABC%20123')
        Pedido.objects.filter(id=self.pedido_ana.id).update(empresa_courier='Courier Desconocido')
        d = self.client.get(url).json()
        self.assertIsNone(d['seguimiento_url'])
        self.assertEqual(d['codigo_seguimiento'], 'ABC 123')

    def test_editar_perfil(self):
        self.client.force_login(self.user_ana)
        r = self.json('patch', '/api/mi-perfil/', {'nombre_completo': '  Ana  María Rojas ', 'telefono': '987654321',
                                                   'email': 'otro@x.cl', 'rut': '33333333-3'})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual((r.json()['nombre_completo'], r.json()['celular']), ('Ana María Rojas', '987654321'))
        self.ana.refresh_from_db()
        self.user_ana.refresh_from_db()
        # Correo y RUT son de solo lectura: se ignoran
        self.assertEqual((self.ana.telefono, self.ana.email, self.ana.rut), ('+56987654321', 'ana@x.cl', '11111111-1'))
        self.assertEqual((self.user_ana.first_name, self.user_ana.last_name), ('Ana', 'María Rojas'))
        for malo in ('12345678', '9876543210', 'abc'):
            self.assertEqual(self.json('patch', '/api/mi-perfil/', {'telefono': malo}).status_code, 400, malo)
        self.assertEqual(self.json('patch', '/api/mi-perfil/', {'nombre_completo': ' '}).status_code, 400)

    def test_cambiar_password(self):
        self.client.force_login(self.user_ana)
        url = '/api/mi-perfil/cambiar-password/'
        r = self.json('post', url, {'password_actual': 'mala', 'password_nueva': 'OtraClave456'})
        self.assertEqual(r.status_code, 400)
        self.assertIn('actual', r.json()['error'])
        r = self.json('post', url, {'password_actual': self.CLAVE, 'password_nueva': '123'})
        self.assertEqual(r.status_code, 400)
        self.assertIn('contraseña', r.json()['error'])  # validadores de Django, en español
        r = self.json('post', url, {'password_actual': self.CLAVE, 'password_nueva': 'OtraClave456'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.client.get('/api/mi-perfil/').status_code, 200)  # la sesión sigue activa
        self.user_ana.refresh_from_db()
        self.assertTrue(self.user_ana.check_password('OtraClave456'))

    def test_eliminar_cuenta(self):
        self.client.force_login(self.user_ana)
        url = '/api/mi-perfil/eliminar-cuenta/'
        self.assertEqual(self.json('post', url, {'password': 'mala'}).status_code, 400)
        self.assertEqual(self.json('post', url, {'password': self.CLAVE}).status_code, 200)
        self.ana.refresh_from_db()
        self.user_ana.refresh_from_db()
        correo = f'eliminado-{self.ana.id}@repuestosrs.invalid'
        self.assertEqual((self.ana.nombre_completo, self.ana.email, self.ana.telefono), ('Cuenta eliminada', correo, ''))
        self.assertNotEqual(self.ana.rut, '11111111-1')
        self.assertFalse(self.user_ana.is_active)
        self.assertEqual(self.user_ana.email, f'eliminado-{self.user_ana.id}@repuestosrs.invalid')
        self.assertFalse(VehiculoCliente.objects.filter(usuario=self.ana).exists())
        self.assertTrue(VehiculoCliente.objects.filter(id=self.veh_beto.id).exists())
        self.assertEqual(Pedido.objects.get(id=self.pedido_ana.id).usuario_id, self.ana.id)  # el pedido se conserva
        # La sesión se cerró y no se puede volver a entrar
        self.assertEqual(self.client.get('/api/mi-perfil/').status_code, 403)
        r = self.json('post', '/api/login/', {'email': 'ana@x.cl', 'password': self.CLAVE})
        self.assertEqual(r.status_code, 401)

    def test_agregar_vehiculo_desde_datos(self):
        self.client.force_login(self.user_ana)
        url = '/api/mis-vehiculos/'
        r = self.json('post', url, {'vehiculo_id': self.veh.id})
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual((r.json()['marca'], r.json()['modelo'], r.json()['anio']), ('Toyota', 'Yaris', '2015-2020'))
        # Duplicado exacto: devuelve el mismo, no crea otro
        r2 = self.json('post', url, {'vehiculo_id': self.veh.id})
        self.assertEqual((r2.status_code, r2.json()['id']), (200, r.json()['id']))
        self.assertEqual(VehiculoCliente.objects.filter(usuario=self.ana, patente__isnull=True).count(), 1)
        self.assertEqual(self.json('post', url, {'vehiculo_id': 99999}).status_code, 400)
        # No aparece en la cuenta de otro cliente
        self.client.force_login(self.user_beto)
        self.assertEqual([v['patente'] for v in self.client.get(url).json()], ['BBBB22'])

    def test_agregar_vehiculo_por_patente(self):
        # mock_vehiculos.json: ABCD12 = Toyota Hilux 2022, 2.8 Diesel
        Vehiculo.objects.create(marca='Toyota', modelo='Hilux', anio_inicio=2005, anio_fin=2015, motorizacion='2.5 Diesel')
        hilux = Vehiculo.objects.create(marca='Toyota', modelo='Hilux', anio_inicio=2016, motorizacion='2.8 Diesel')
        self.client.force_login(self.user_ana)
        r = self.json('post', '/api/mis-vehiculos/', {'patente': 'abcd-12', 'marca': 'Ferrari'})  # la marca del navegador se ignora
        self.assertEqual(r.status_code, 201, r.content)
        v = VehiculoCliente.objects.get(id=r.json()['id'])
        self.assertEqual((v.vehiculo_base, v.patente, v.vin), (hilux, 'ABCD12', 'ABCD1234567890VIN'))
        self.assertEqual(self.json('post', '/api/mis-vehiculos/', {'patente': 'ABCD12'}).status_code, 200)  # duplicado
        self.assertEqual(self.json('post', '/api/mis-vehiculos/', {'patente': 'ZZZZ00'}).status_code, 404)
        # La misma patente en otra cuenta: conflicto, no se crea ni se muestra
        self.client.force_login(self.user_beto)
        self.assertEqual(self.json('post', '/api/mis-vehiculos/', {'vin': 'ABCD1234567890VIN'}).status_code, 409)
        self.assertEqual(VehiculoCliente.objects.filter(patente='ABCD12').count(), 1)
        self.assertNotIn('ABCD12', [x['patente'] for x in self.client.get('/api/mis-vehiculos/').json()])

    def test_agregar_vehiculo_anonimo_403(self):
        r = self.json('post', '/api/mis-vehiculos/', {'vehiculo_id': self.veh.id})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(VehiculoCliente.objects.count(), 2)

    def test_registro_valida_telefono(self):
        datos = {'rut': '33333333-3', 'nombre_completo': 'Carla Díaz', 'email': 'carla@x.cl', 'password': self.CLAVE}
        for malo in ('12345678', '+5691234567', 'abc'):
            r = self.json('post', '/api/register/', {**datos, 'telefono': malo})
            self.assertEqual(r.status_code, 400, malo)
            self.assertIn('teléfono', r.json()['error'])
        self.assertFalse(Usuario.objects.filter(email='carla@x.cl').exists())
        # Lo que envía el formulario hoy: +56 y 9 dígitos
        self.assertEqual(self.json('post', '/api/register/', {**datos, 'telefono': '+56912345678'}).status_code, 201)
        self.assertEqual(Usuario.objects.get(email='carla@x.cl').telefono, '+56912345678')

    def test_admin_no_se_elimina(self):
        admin = User.objects.create_user('jefe@x.cl', 'jefe@x.cl', self.CLAVE, is_staff=True)
        self.client.force_login(admin)
        r = self.json('post', '/api/mi-perfil/eliminar-cuenta/', {'password': self.CLAVE})
        self.assertEqual(r.status_code, 403)
        self.assertIn('administrador', r.json()['error'])
        admin.refresh_from_db()
        self.assertTrue(admin.is_active)
