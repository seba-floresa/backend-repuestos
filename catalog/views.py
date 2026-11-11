from rest_framework import viewsets, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAdminUser

from .models import Repuesto, Categoria, Pedido
from .serializers import RepuestoSerializer, CategoriaSerializer, PedidoSerializer
from .services.vin_service import MockBuscadorVehiculo

class CategoriaViewSet(viewsets.ModelViewSet):
    queryset = Categoria.objects.all()
    serializer_class = CategoriaSerializer

class RepuestoViewSet(viewsets.ModelViewSet):
    queryset = Repuesto.objects.all()
    serializer_class = RepuestoSerializer
    permission_classes = [IsAdminUser] # Exige que la petición HTTP venga de un usuario staff real

class PedidoViewSet(viewsets.ModelViewSet):
    queryset = Pedido.objects.all()
    serializer_class = PedidoSerializer


class BuscarVehiculoAPIView(APIView):
    """
    Endpoint para buscar vehículos por Patente o VIN utilizando el Patrón Adaptador.
    """
    def get(self, request):
        # Capturamos el parámetro 'q' de la URL (ej: /api/buscar-vehiculo/?q=ABCD12)
        identificador = request.query_params.get('q', '').strip()
        
        if not identificador:
            return Response(
                {"error": "Debe proporcionar una patente o VIN en el parámetro 'q'."}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        # Patrón adaptador instanciado
        buscador = MockBuscadorVehiculo()
        resultado = buscador.buscar(identificador)

        if resultado:
            return Response(resultado, status=status.HTTP_200_OK)
        else:
            return Response(
                {"error": "Vehículo no encontrado en los registros."}, 
                status=status.HTTP_404_NOT_FOUND
            )