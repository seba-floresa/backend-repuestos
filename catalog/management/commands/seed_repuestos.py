"""
Carga repuestos de prueba (3 por subcategoría) para la demo.

Uso (desde la carpeta del backend, con el entorno virtual activo):

    python manage.py seed_repuestos              # crea/actualiza los repuestos
    python manage.py seed_repuestos --sin-imagenes
    python manage.py seed_repuestos --borrar     # borra solo los repuestos creados por este comando

- Lee las categorías y subcategorías que YA existen en tu base de datos.
- Es idempotente: se puede ejecutar varias veces sin duplicar (usa el SKU).
- No toca los repuestos que creaste a mano (sus SKU no siguen este patrón).
- Los productos no universales se asocian a vehículos que ya existan en tu tabla Vehiculo.
"""
import io
import random
import re
import unicodedata

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction

from catalog.models import (
    Categoria,
    CompatibilidadVehicular,
    Repuesto,
    Subcategoria,
    Vehiculo,
)


def norm(texto):
    """Minúsculas y sin tildes, para comparar nombres."""
    texto = unicodedata.normalize('NFD', texto or '')
    return ''.join(c for c in texto if unicodedata.category(c) != 'Mn').lower()


def N(nombre, marca, precio, oem, peso=1.0, universal=False):
    """Producto NUEVO."""
    return dict(nombre=nombre, marca=marca, precio=precio, oem=oem, peso=peso,
                condicion='NUEVO', desgaste='', universal=universal)


def D(nombre, marca, precio, oem, peso, condicion, desgaste):
    """Producto de DESARMADURÍA (USADO / REACONDICIONADO)."""
    return dict(nombre=nombre, marca=marca, precio=precio, oem=oem, peso=peso,
                condicion=condicion, desgaste=desgaste, universal=False)


# (palabra de la categoría, palabras de la subcategoría, [3 productos])
# Se usa la primera plantilla que coincida. Subcategoría () = cualquiera de esa categoría.
PLANTILLAS = [
    # ---------------- FILTROS ----------------
    ('filtro', ('aceite',), [
        N('Filtro de aceite roscado', 'Sakura', 6990, '26300-35503', 0.4),
        N('Filtro de aceite', 'Bosch', 8490, '15208-65F0C', 0.45),
        N('Filtro de aceite blindado', 'Mann-Filter', 11990, '90915-YZZJ1', 0.5)]),
    ('filtro', ('aire',), [
        N('Filtro de aire de motor', 'Mann-Filter', 12990, '28113-1R100', 0.3),
        N('Filtro de aire de motor', 'Denso', 14490, '17801-0Y050', 0.3),
        N('Filtro de aire deportivo lavable', 'K&N', 38990, '33-2960', 0.4)]),
    ('filtro', ('combustible', 'bencina', 'petroleo'), [
        N('Filtro de combustible en línea', 'Mahle', 11490, '96335719', 0.35),
        N('Filtro de combustible', 'Bosch', 13990, '31911-2E000', 0.4),
        N('Filtro de combustible', 'Sakura', 9990, '23300-0L041', 0.35)]),
    ('filtro', ('polen', 'cabina', 'habitaculo'), [
        N('Filtro de polen carbón activado', 'Bosch', 9990, '97133-1R000', 0.2),
        N('Filtro de cabina antipolen', 'Mann-Filter', 8990, 'CU-2243', 0.2),
        N('Filtro de polen', 'Sakura', 7490, '87139-0D020', 0.2)]),

    # ---------------- ACEITE ----------------
    ('aceite', ('motor',), [
        N('Aceite de motor 5W-30 sintético 4 L', 'Castrol Edge', 38990, 'ACEA-C3-5W30', 3.6, True),
        N('Aceite de motor 10W-40 semisintético 4 L', 'Shell Helix HX7', 27990, 'API-SN-10W40', 3.6, True),
        N('Aceite de motor 20W-50 mineral 4 L', 'Mobil Super', 21990, 'API-SL-20W50', 3.6, True)]),
    ('aceite', ('transmision', 'caja', 'atf', 'cvt'), [
        N('Fluido ATF Dexron VI 1 L', 'Valvoline', 9990, 'DEXRON-VI', 0.9, True),
        N('Aceite de caja manual 75W-90 1 L', 'Castrol', 12990, 'GL4-75W90', 0.9, True),
        N('Fluido CVT universal 4 L', 'Liqui Moly', 54990, 'CVT-NS3', 3.6, True)]),
    ('aceite', ('aditivo',), [
        N('Limpiador de inyectores 325 ml', "Wynn's", 7490, 'WYN-INY-325', 0.4, True),
        N('Tratamiento antifricción de motor', 'Liqui Moly', 15990, 'LM-2001', 0.5, True),
        N('Limpiador de sistema de combustible', 'Gumout', 8990, 'GM-510', 0.4, True)]),
    ('aceite', ('direccion', 'hidraul'), [
        N('Fluido hidráulico de dirección 1 L', 'Valvoline', 8990, 'PSF-1L', 0.9, True),
        N('Fluido de dirección asistida 500 ml', 'Castrol', 6490, 'PSF-500', 0.5, True),
        N('Fluido hidráulico ATF/PSF 1 L', 'Liqui Moly', 10990, 'LM-PSF1', 0.9, True)]),

    # ---------------- FRENOS ----------------
    ('freno', ('pastilla',), [
        N('Pastillas de freno delanteras', 'Bosch', 24990, '58101-1RA00', 1.0),
        N('Pastillas de freno delanteras', 'Frasle', 21990, '04465-52120', 1.0),
        N('Pastillas de freno traseras cerámicas', 'Brembo', 39990, 'P-23134', 0.8)]),
    ('freno', ('disco',), [
        N('Disco de freno ventilado delantero (par)', 'TRW', 59990, 'BBM2-33-251', 8.0),
        N('Disco de freno trasero sólido (par)', 'Brembo', 48990, '08A11411', 5.0),
        N('Disco de freno perforado delantero (par)', 'Frasle', 69990, 'DF-4410', 8.0)]),
    ('freno', ('bomba', 'cilindro'), [
        N('Bomba principal de freno', 'ATE', 68990, '46010-68L10', 1.5),
        N('Cilindro de rueda trasero', 'TRW', 14990, 'BWH-117', 0.5),
        N('Cilindro maestro de embrague', 'LuK', 45990, 'CMC-220', 1.2)]),
    ('freno', ('liquido',), [
        N('Líquido de frenos DOT 4 · 500 ml', 'Bosch', 5990, 'DOT-4-500', 0.5, True),
        N('Líquido de frenos DOT 5.1 · 1 L', 'Castrol', 11990, 'DOT-51-1L', 1.0, True),
        N('Líquido de frenos DOT 3 · 500 ml', 'Wagner', 4990, 'DOT-3-500', 0.5, True)]),
    ('freno', ('zapata', 'balata', 'tambor'), [
        N('Zapatas de freno traseras', 'Frasle', 17990, '04495-0K020', 1.2),
        N('Juego de zapatas de freno', 'Bosch', 19990, 'BS-0986', 1.2),
        N('Tambor de freno trasero', 'TRW', 34990, 'DB-4408', 4.5)]),

    # ---------------- ENCENDIDO ----------------
    ('encend', ('bujia',), [
        N('Bujías de iridio (juego de 4)', 'NGK', 32990, 'ILKR7B-11', 0.3),
        N('Bujías de platino (juego de 4)', 'Denso', 27990, 'PK20TT', 0.3),
        N('Bujías de cobre estándar (juego de 4)', 'Bosch', 15990, 'FR7DC', 0.3)]),
    ('encend', ('bobina',), [
        N('Bobina de encendido', 'Delphi', 29990, '55577898', 0.4),
        N('Bobina de encendido', 'Bosch', 34990, '0221504470', 0.4),
        N('Bobina de encendido tipo lápiz', 'NGK', 31990, 'U5013', 0.3)]),
    ('encend', ('cable',), [
        N('Juego de cables de bujía', 'Bosch', 22490, '33705-80J10', 0.6),
        N('Juego de cables de bujía', 'NGK', 24990, 'RC-HE79', 0.6),
        N('Juego de cables de bujía', 'Denso', 21990, 'DWC-102', 0.6)]),

    # ---------------- REFRIGERACIÓN ----------------
    ('refriger', ('radiador',), [
        N('Radiador de aluminio', 'Valeo', 89990, '25310-1R000', 4.5),
        N('Radiador de cobre-latón', 'Nissens', 79990, 'NR-6310', 5.0),
        N('Radiador con tapa y sensor', 'Denso', 94990, 'DR-2105', 4.8)]),
    ('refriger', ('bomba',), [
        N('Bomba de agua', 'GMB', 34990, '16100-09540', 1.5),
        N('Bomba de agua con carcasa', 'Aisin', 42990, 'WPT-182', 1.8),
        N('Bomba de agua eléctrica auxiliar', 'Bosch', 58990, '0392022010', 1.0)]),
    ('refriger', ('termostato',), [
        N('Termostato con empaquetadura', 'Wahler', 12990, '96984103', 0.3),
        N('Termostato 82 °C', 'Gates', 14990, 'TH-33987', 0.3),
        N('Termostato con carcasa', 'Stant', 11990, 'ST-14048', 0.4)]),
    ('refriger', ('ventilador', 'electroventilador'), [
        N('Electroventilador de radiador', 'Nissens', 74990, 'BP4K-15-025', 3.5),
        N('Aspa de ventilador', 'Valeo', 29990, 'VA-4402', 1.0),
        N('Embrague de ventilador viscoso', 'Hayden', 46990, 'HY-2748', 2.0)]),
    ('refriger', ('manguera',), [
        N('Manguera superior de radiador', 'Gates', 14990, 'GT-24221', 0.5),
        N('Manguera inferior de radiador', 'Gates', 15990, 'GT-24222', 0.5),
        N('Juego de abrazaderas y mangueras', 'Dayco', 24990, 'DY-7710', 0.8)]),
    ('refriger', ('refrigerante', 'anticongelante', 'liquido'), [
        N('Refrigerante concentrado 1 galón', 'Prestone', 12990, 'AF-2000', 3.8, True),
        N('Refrigerante listo para usar 1 galón', 'Castrol', 14990, 'AF-RTU', 3.8, True),
        N('Anticongelante orgánico 1 L', 'Liqui Moly', 8990, 'LM-ANT1', 1.0, True)]),

    # ---------------- DESARMADURÍA ----------------
    ('desarm', ('motor', 'culata'), [
        D('Motor completo 1.4 L · 98.000 km', 'Original Kia', 1290000, 'G4FA', 95.0, 'REACONDICIONADO',
          '98.000 km verificados. Compresión pareja en los 4 cilindros, retenes cambiados. Sin fugas visibles. Incluye múltiple de admisión.'),
        D('Culata 1.6 L con árbol de levas', 'Original Hyundai', 210000, '22100-2B000', 18.0, 'USADO',
          'Superficie planeada, sin fisuras. Válvulas con buen asiento. Pendiente el cambio de retenes de válvula.'),
        D('Motor 1.5 L diésel · 120.000 km', 'Original Chevrolet', 980000, 'Z15D', 110.0, 'USADO',
          '120.000 km. Sin humo azul ni blanco al arrancar. Turbo con leve juego axial, dentro de tolerancia.')]),
    ('desarm', ('caja', 'transmision', 'diferencial', 'embrague'), [
        D('Caja de cambios manual 5 velocidades', 'Original Chevrolet', 320000, 'MT-5V-SAIL', 38.0, 'USADO',
          'Sincronizadores en buen estado. Leve ruido en 2ª marcha en frío que desaparece al calentar. Sin fugas por retenes.'),
        D('Caja automática 4 velocidades', 'Original Hyundai', 540000, '45000-26000', 62.0, 'REACONDICIONADO',
          'Reacondicionada: kit de empaquetaduras y filtro nuevos. Cambios suaves en banco de pruebas. Sin convertidor de torque.'),
        D('Diferencial trasero completo', 'Original Toyota', 150000, '41110-0K050', 28.0, 'USADO',
          'Sin juego excesivo en piñón y corona. Aceite sin limalla. Leve rayadura en la tapa.')]),
    ('desarm', ('optica', 'faro', 'foco', 'luz', 'luces'), [
        D('Óptica delantera derecha', 'Original Hyundai', 45000, '92102-1R500', 1.8, 'USADO',
          'Lente sin rayas profundas, leve opacidad en la esquina inferior. Soportes completos y sin quebraduras. Probada con ampolleta.'),
        D('Óptica trasera izquierda', 'Original Kia', 28000, '92401-1R000', 1.2, 'USADO',
          'Sin rajaduras ni humedad interior. Porta-ampolletas completo. Un soporte con fisura menor.'),
        D('Foco antiniebla delantero', 'Original Toyota', 15000, '81220-0D010', 0.6, 'USADO',
          'Cristal sin picaduras. Conector en buen estado. Marco con rayas leves.')]),
    ('desarm', ('carroceria', 'capo', 'puerta', 'panel', 'parachoque', 'guardabarro', 'espejo'), [
        D('Capó delantero', 'Original Toyota', 85000, '66400-0D010', 12.0, 'USADO',
          'Golpe de ~3 cm en el costado izquierdo, sin óxido ni pintura saltada. Bisagras y tope de goma en buen estado. Requiere pintura.'),
        D('Puerta delantera izquierda', 'Original Hyundai', 120000, '76003-1R000', 22.0, 'USADO',
          'Sin óxido. Pequeña abolladura inferior sin deformar el marco. Incluye elevalunas eléctrico funcionando.'),
        D('Parachoques delantero', 'Original Kia', 65000, '86511-1R000', 6.0, 'USADO',
          'Rayones superficiales y una pestaña de fijación reparada. Sin quebraduras visibles.')]),
    ('desarm', ('interior', 'electr', 'tablero', 'asiento', 'alternador', 'computador'), [
        D('Alternador 90 A', 'Original Hyundai', 55000, '37300-2B100', 4.5, 'REACONDICIONADO',
          'Reacondicionado: escobillas, regulador y rodamientos nuevos. Probado en banco a 90 A. Carcasa con marcas de uso normal.'),
        D('Computador de motor (ECU)', 'Original Suzuki', 120000, '33920-62J10', 0.8, 'USADO',
          'Carcasa sin golpes ni humedad, conectores sin pines doblados. Requiere programación con el inmovilizador del vehículo receptor.'),
        D('Tablero de instrumentos', 'Original Chevrolet', 75000, '95937-5A', 1.5, 'USADO',
          'Pantalla y agujas funcionando. Cubierta transparente con rayas finas. Kilometraje no certificado.')]),
    ('desarm', ('suspension', 'amortiguador', 'direccion'), [
        D('Amortiguador delantero', 'Original Toyota', 38000, '48510-09M40', 3.0, 'USADO',
          'Vástago sin picaduras, sin fuga de aceite. Resorte incluido. Gomas del soporte con desgaste normal.'),
        D('Caja de dirección hidráulica', 'Original Hyundai', 95000, '57700-1R000', 11.0, 'REACONDICIONADO',
          'Reacondicionada: retenes y fuelles nuevos. Sin juego en la cremallera. Probada con presión.'),
        D('Brazo de suspensión inferior', 'Original Kia', 32000, '54500-1R000', 4.0, 'USADO',
          'Sin deformaciones. Buje original con leve desgaste, recomendado cambiar.')]),
]

# Marcas y precios base para subcategorías que no calzan con ninguna plantilla
GENERICOS = {
    'filtro': ('Bosch', 'Mann-Filter', 'Sakura'),
    'aceite': ('Castrol', 'Shell', 'Valvoline'),
    'freno': ('Bosch', 'Frasle', 'TRW'),
    'encend': ('NGK', 'Bosch', 'Denso'),
    'refriger': ('Valeo', 'Gates', 'Nissens'),
    'desarm': ('Original Toyota', 'Original Hyundai', 'Original Chevrolet'),
}
PRECIOS_GENERICOS = (14990, 24990, 39990)

CODIGO_CATEGORIA = {'filtro': 'FIL', 'aceite': 'ACE', 'freno': 'FRE',
                    'encend': 'ENC', 'refriger': 'REF'}

COLORES_CATEGORIA = {
    'filtro': ((219, 232, 255), (29, 78, 216)),
    'aceite': ((255, 240, 199), (161, 98, 7)),
    'freno': ((255, 223, 220), (180, 35, 24)),
    'encend': ((231, 222, 252), (91, 33, 182)),
    'refriger': ((212, 241, 238), (15, 118, 110)),
    'desarm': ((236, 227, 212), (107, 68, 35)),
}

PATRON_SKU_SEMILLA = r'^(RS|DES)-[A-Z0-9]{3}-\d{3,4}$'


def clave_categoria(nombre_categoria):
    n = norm(nombre_categoria)
    for clave in GENERICOS:
        if clave in n:
            return clave
    return None


def elegir_plantilla(categoria, subcategoria):
    """Devuelve (lista_de_3_productos, es_generica)."""
    ncat, nsub = norm(categoria), norm(subcategoria)
    for cat_kw, sub_kws, productos in PLANTILLAS:
        if cat_kw in ncat and any(k in nsub for k in sub_kws):
            return productos, False

    clave = clave_categoria(categoria) or 'filtro'
    marcas = GENERICOS[clave]
    productos = []
    for i in range(3):
        nombre = f'{subcategoria} · línea {i + 1}'
        if clave == 'desarm':
            productos.append(D(nombre, marcas[i], PRECIOS_GENERICOS[i] * 3, '', 5.0,
                               'USADO' if i != 1 else 'REACONDICIONADO',
                               'Pieza original en buen estado general, con marcas leves de uso. Probada antes de la venta.'))
        else:
            productos.append(N(nombre, marcas[i], PRECIOS_GENERICOS[i], '', 1.0))
    return productos, True


def abreviatura(texto, largo=3):
    letras = re.sub(r'[^a-z]', '', norm(texto))
    return (letras[:largo] or 'GEN').upper().ljust(largo, 'X')


def generar_imagen(producto, sku, clave_cat):
    """Crea una imagen PNG simple (placeholder referencial). Devuelve bytes o None si no hay Pillow."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return None

    fondo, tinta = COLORES_CATEGORIA.get(clave_cat, ((230, 230, 230), (60, 60, 60)))
    ancho, alto = 600, 450
    img = Image.new('RGB', (ancho, alto), fondo)
    dib = ImageDraw.Draw(img)

    def fuente(tam):
        try:
            return ImageFont.load_default(size=tam)
        except TypeError:  # Pillow antiguo sin parámetro size
            return ImageFont.load_default()

    # Círculo decorativo
    dib.ellipse((ancho // 2 - 90, 40, ancho // 2 + 90, 220), fill=tinta)
    dib.ellipse((ancho // 2 - 55, 75, ancho // 2 + 55, 185), fill=fondo)
    dib.ellipse((ancho // 2 - 18, 112, ancho // 2 + 18, 148), fill=tinta)

    # Nombre con salto de línea
    f_nombre, f_chica = fuente(30), fuente(20)
    palabras, lineas, actual = producto['nombre'].split(), [], ''
    for p in palabras:
        prueba = f'{actual} {p}'.strip()
        if dib.textlength(prueba, font=f_nombre) <= ancho - 60:
            actual = prueba
        else:
            lineas.append(actual)
            actual = p
    lineas.append(actual)
    y = 245
    for linea in lineas[:3]:
        w = dib.textlength(linea, font=f_nombre)
        dib.text(((ancho - w) / 2, y), linea, fill=tinta, font=f_nombre)
        y += 38

    pie = f"{producto['marca']}  ·  {sku}"
    w = dib.textlength(pie, font=f_chica)
    dib.text(((ancho - w) / 2, alto - 70), pie, fill=tinta, font=f_chica)

    if producto['condicion'] != 'NUEVO':
        dib.rectangle((0, alto - 36, ancho, alto), fill=tinta)
        etiqueta = 'FOTO REFERENCIAL · DESARMADURÍA'
        w = dib.textlength(etiqueta, font=f_chica)
        dib.text(((ancho - w) / 2, alto - 31), etiqueta, fill=(255, 255, 255), font=f_chica)
    else:
        etiqueta = 'imagen referencial'
        w = dib.textlength(etiqueta, font=f_chica)
        dib.text(((ancho - w) / 2, alto - 32), etiqueta, fill=tinta, font=f_chica)

    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    return buffer.getvalue()


class Command(BaseCommand):
    help = 'Crea 3 repuestos de prueba por cada subcategoría existente (idempotente).'

    def add_arguments(self, parser):
        parser.add_argument('--sin-imagenes', action='store_true',
                            help='No generar imágenes de ejemplo.')
        parser.add_argument('--borrar', action='store_true',
                            help='Borra los repuestos creados por este comando y termina.')

    @transaction.atomic
    def handle(self, *args, **opciones):
        if opciones['borrar']:
            qs = Repuesto.objects.filter(sku__regex=PATRON_SKU_SEMILLA)
            total = qs.count()
            qs.delete()
            self.stdout.write(self.style.WARNING(f'Se borraron {total} repuestos de prueba.'))
            return

        subcategorias = list(Subcategoria.objects.select_related('categoria').order_by('categoria_id', 'id'))
        if not subcategorias:
            self.stdout.write(self.style.ERROR(
                'No hay subcategorías en la base de datos. Créalas primero (panel o Django Admin).'))
            return

        vehiculos = list(Vehiculo.objects.all())
        if not vehiculos:
            self.stdout.write(self.style.WARNING(
                'No hay vehículos creados: los repuestos se crearán sin compatibilidad.'))

        creados = actualizados = genericas = 0

        for sub in subcategorias:
            cat = sub.categoria
            clave = clave_categoria(cat.nombre)
            es_des = clave == 'desarm'
            productos, generica = elegir_plantilla(cat.nombre, sub.nombre)
            if generica:
                genericas += 1
                self.stdout.write(self.style.WARNING(
                    f'  · "{cat.nombre} › {sub.nombre}": sin plantilla específica, se usaron nombres genéricos.'))

            for n, prod in enumerate(productos, start=1):
                if es_des:
                    sku = f'DES-{abreviatura(sub.nombre)}-{sub.id:02d}{n}'
                else:
                    sku = f'RS-{CODIGO_CATEGORIA.get(clave, abreviatura(cat.nombre))}-{sub.id:02d}{n}'

                rnd = random.Random(sku)
                if es_des:
                    stock = rnd.choice([1, 1, 2])
                else:
                    stock = rnd.choice([2, 3, 5, 8, 12, 15, 20, 30])

                oem = prod['oem'] or f'{abreviatura(sub.nombre)}-{sub.id:02d}{n}-{rnd.randint(1000, 9999)}'

                repuesto, creado = Repuesto.objects.update_or_create(
                    sku=sku,
                    defaults=dict(
                        categoria=cat,
                        subcategoria=sub,
                        nombre=prod['nombre'],
                        marca_fabricante=prod['marca'],
                        precio_unitario=prod['precio'],
                        peso_kg=prod['peso'],
                        stock_disponible=stock,
                        condicion=prod['condicion'],
                        detalle_desgaste=prod['desgaste'] or None,
                        codigo_oem=oem,
                        activo=True,
                    ),
                )
                creados += creado
                actualizados += (not creado)

                # Compatibilidad vehicular (los universales no llevan)
                CompatibilidadVehicular.objects.filter(repuesto=repuesto).delete()
                if vehiculos and not prod['universal']:
                    cuantos = min(len(vehiculos), rnd.choice([1, 2, 3]))
                    for v in rnd.sample(vehiculos, cuantos):
                        CompatibilidadVehicular.objects.create(
                            repuesto=repuesto,
                            vehiculo=v,
                            anio_desde=v.anio_inicio,
                            anio_hasta=v.anio_fin if v.anio_fin else v.anio_inicio,
                        )

                # Imagen de ejemplo (solo si aún no tiene una)
                if not opciones['sin_imagenes'] and not repuesto.imagen:
                    datos = generar_imagen(prod, sku, clave)
                    if datos:
                        repuesto.imagen.save(f'{sku}.png', ContentFile(datos), save=True)

        self.stdout.write(self.style.SUCCESS(
            f'Listo: {creados} repuestos creados, {actualizados} actualizados '
            f'({len(subcategorias)} subcategorías, {genericas} con nombres genéricos).'))
