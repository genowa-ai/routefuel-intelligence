from rest_framework import serializers

class RouteFuelRequestSerializer(serializers.Serializer):
    start_location = serializers.CharField(max_length=200, trim_whitespace=True)
    finish_location = serializers.CharField(max_length=200, trim_whitespace=True)

    def validate(self, attrs):
        start = attrs["start_location"].casefold()
        finish = attrs["finish_location"].casefold()
        if start == finish:
            raise serializers.ValidationError({"finish_location": "Start and finish must be different locations."})
        return attrs
