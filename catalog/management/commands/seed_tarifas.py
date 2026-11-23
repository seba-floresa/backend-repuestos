from django.core.management.base import BaseCommand

from catalog.models import TarifaDespacho

# (región, comuna, costo por kg en CLP, días hábiles estimados)
TARIFAS = [
    ('Región Metropolitana', 'Santiago', 3500, 1),
    ('Región Metropolitana', 'Providencia', 3500, 1),
    ('Región Metropolitana', 'Las Condes', 3500, 1),
    ('Región Metropolitana', 'Maipú', 3500, 1),
    ('Región Metropolitana', 'Puente Alto', 3800, 2),
    ('Valparaíso', 'Valparaíso', 4500, 2),
    ('Valparaíso', 'Viña del Mar', 4500, 2),
    ('Biobío', 'Concepción', 5500, 3),
    ('Biobío', 'Los Ángeles', 5800, 3),
    ('Coquimbo', 'La Serena', 5500, 3),
    ('Antofagasta', 'Antofagasta', 7500, 4),
    ('Los Lagos', 'Puerto Montt', 7000, 4),
]


class Command(BaseCommand):
    help = 'Carga tarifas de despacho de ejemplo (se puede ejecutar varias veces).'

    def handle(self, *args, **options):
        for region, comuna, costo, dias in TARIFAS:
            TarifaDespacho.objects.update_or_create(
                comuna=comuna,
                defaults={'region': region, 'costo_base_kg': costo, 'dias_habiles_estimados': dias},
            )
        self.stdout.write(self.style.SUCCESS(f'{len(TARIFAS)} tarifas de despacho listas.'))