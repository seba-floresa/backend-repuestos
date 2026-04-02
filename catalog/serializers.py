from rest_framework import serializers
from .models import Product, Vehicle, Category

class VehicleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Vehicle
        fields = '__all__'
        depth = 2  # Truco: Muestra los nombres (Toyota) en vez de los IDs (1)

class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = '__all__'

class ProductSerializer(serializers.ModelSerializer):
    # Aquí incrustamos la info detallada de los autos compatibles
    compatible_vehicles = VehicleSerializer(many=True, read_only=True)
    category = CategorySerializer(read_only=True)

    class Meta:
        model = Product
        fields = '__all__'