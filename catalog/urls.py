from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import RepuestoViewSet, CategoriaViewSet, PedidoViewSet, BuscarVehiculoAPIView

router = DefaultRouter()
router.register(r'categorias', CategoriaViewSet)
router.register(r'repuestos', RepuestoViewSet)
router.register(r'pedidos', PedidoViewSet)

urlpatterns = [
    # Rutas automáticas del CRUD
    path('', include(router.urls)),
    # Ruta personalizada para la búsqueda de patentes/VIN
    path('buscar-vehiculo/', BuscarVehiculoAPIView.as_view(), name='buscar-vehiculo'),
]