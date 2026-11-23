from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    RepuestoViewSet,
    CategoriaViewSet,
    SubcategoriaViewSet,
    VehiculoViewSet,
    PedidoViewSet,
    BuscarVehiculoAPIView,
    checkout_api_view,
    login_api_view,
    mi_perfil_api_view,
    register_api_view,
    solicitud_repuesto_api_view,
    logout_api_view,
    tarifas_despacho_api_view,
    webpay_retorno_view,
)

router = DefaultRouter()
router.register(r'categorias', CategoriaViewSet)
router.register(r'subcategorias', SubcategoriaViewSet)
router.register(r'vehiculos', VehiculoViewSet)
router.register(r'repuestos', RepuestoViewSet)
router.register(r'pedidos', PedidoViewSet)

urlpatterns = [
    # Rutas automáticas del CRUD
    path('', include(router.urls)),
    # Ruta personalizada para la búsqueda de patentes/VIN
    path('buscar-vehiculo/', BuscarVehiculoAPIView.as_view(), name='buscar-vehiculo'),
    path('login/', login_api_view, name='api-login'),
    path('logout/', logout_api_view, name='api-logout'),
    path('register/', register_api_view, name='api-register'),
    path('solicitudes/', solicitud_repuesto_api_view, name='api-solicitudes'),
    path('tarifas-despacho/', tarifas_despacho_api_view, name='api-tarifas'),
    path('checkout/', checkout_api_view, name='api-checkout'),
    path('webpay/retorno/', webpay_retorno_view, name='webpay-retorno'),
    path('mi-perfil/', mi_perfil_api_view, name='api-mi-perfil'),
]