from django.http import JsonResponse
from django.shortcuts import render
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from .serializers import RouteFuelRequestSerializer
from .services.planner import plan_fuel_route


def health(request):
    return JsonResponse({"status": "ok", "service": "fuel-route-optimizer"})


def map_preview(request):
    return render(request, "routefuel/map.html")


class RouteFuelAPIView(APIView):
    """Plan one US drive and return GeoJSON plus cost-oriented fuel stops."""
    def post(self, request, *args, **kwargs):
        serializer = RouteFuelRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = plan_fuel_route(**serializer.validated_data)
        if result["fuel_plan"]["status"] == "unreachable":
            return Response(result, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response(result, status=status.HTTP_200_OK)
