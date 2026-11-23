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