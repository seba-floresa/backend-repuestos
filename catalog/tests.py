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
        for estado in ['PENDIENTE', 'RESPONDIDA']:
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