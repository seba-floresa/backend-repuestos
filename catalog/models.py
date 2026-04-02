from django.db import models

# 1. Marcas (Toyota, Kia)
class CarMake(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name="Marca")
    def __str__(self): return self.name

# 2. Modelos (Yaris, Rio)
class CarModel(models.Model):
    make = models.ForeignKey(CarMake, on_delete=models.CASCADE, verbose_name="Marca")
    name = models.CharField(max_length=100, verbose_name="Modelo")
    def __str__(self): return f"{self.make.name} - {self.name}"

# 3. Años (2018, 2022)
class CarYear(models.Model):
    year = models.IntegerField(unique=True, verbose_name="Año")
    def __str__(self): return str(self.year)

# 4. Vehículo Único (Toyota Yaris 2018)
class Vehicle(models.Model):
    car_model = models.ForeignKey(CarModel, on_delete=models.CASCADE, verbose_name="Modelo")
    year = models.ForeignKey(CarYear, on_delete=models.CASCADE, verbose_name="Año")
    
    class Meta:
        verbose_name = "Vehículo"
        unique_together = ('car_model', 'year') # Evita duplicados

    def __str__(self):
        return f"{self.car_model.make.name} {self.car_model.name} ({self.year.year})"

# 5. Categoría (Filtros, Frenos)
class Category(models.Model):
    name = models.CharField(max_length=100)
    def __str__(self): return self.name

# 6. PRODUCTO (El Repuesto)
class Product(models.Model):
    sku = models.CharField(max_length=50, unique=True, verbose_name="SKU")
    name = models.CharField(max_length=255, verbose_name="Nombre")
    price = models.PositiveIntegerField(verbose_name="Precio")
    stock = models.PositiveIntegerField(default=0)
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True)
    
    # LA CLAVE: Relación Muchos a Muchos
    compatible_vehicles = models.ManyToManyField(Vehicle, blank=True, verbose_name="Autos Compatibles")
    
    image = models.ImageField(upload_to='products/', null=True, blank=True, verbose_name="Imagen del Repuesto")

    def __str__(self): return self.name