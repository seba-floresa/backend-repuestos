from django.contrib import admin
from .models import CarMake, CarModel, CarYear, Vehicle, Category, Product

admin.site.register(CarMake)
admin.site.register(CarModel)
admin.site.register(CarYear)
admin.site.register(Vehicle)
admin.site.register(Category)
admin.site.register(Product)