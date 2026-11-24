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

    def test_hoy_y_todo(self):
        self.client.force_login(_admin())
        self.assertEqual(len(self.client.get(self.URL + '?periodo=hoy').json()['ventas_por_dia']), 1)
        todo = self.client.get(self.URL + '?periodo=todo').json()
        self.assertEqual(todo['ventas_totales'], 13000)
        self.assertEqual(todo['mas_vendidos'][0]['nombre'], 'B')
        self.assertGreaterEqual(len(todo['ventas_por_dia']), 60)