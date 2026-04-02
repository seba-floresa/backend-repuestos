from rest_framework import generics
from .models import Product
from .serializers import ProductSerializer

class ProductListAPI(generics.ListAPIView):
    serializer_class = ProductSerializer

    def get_queryset(self):
        """
        Este método se ejecuta cada vez que alguien llama a la API.
        Aquí es donde filtramos los repuestos según el auto del cliente.
        """
        queryset = Product.objects.all() # Empieza con TODOS los productos

        # 1. Capturamos lo que viene en la URL (ej: ?make=Toyota&model=Yaris)
        make_name = self.request.query_params.get('make', None)
        model_name = self.request.query_params.get('model', None)
        year_value = self.request.query_params.get('year', None)

        # 2. Si el cliente eligió una Marca, filtramos
        if make_name:
            queryset = queryset.filter(compatible_vehicles__car_model__make__name__iexact=make_name)

        # 3. Si eligió Modelo, filtramos más
        if model_name:
            queryset = queryset.filter(compatible_vehicles__car_model__name__iexact=model_name)

        # 4. Si eligió Año, filtramos aún más
        if year_value:
            queryset = queryset.filter(compatible_vehicles__year__year=year_value)

        # El 'distinct()' es clave: evita que salgan duplicados si un repuesto
        # sirve para varios modelos que coinciden con la búsqueda.
        return queryset.distinct()