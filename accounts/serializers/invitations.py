"""Invitation creation and redemption serializers."""

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from accounts.models import Invitation

User = get_user_model()


class InvitationSerializer(serializers.ModelSerializer):
    token = serializers.CharField(read_only=True)
    is_active = serializers.BooleanField(read_only=True)
    target_kind = serializers.CharField(read_only=True)

    class Meta:
        model = Invitation
        fields = ["id", "house", "project", "target_kind", "label", "created_by", "created_at", "expires_at", "revoked_at", "uses", "last_used_at", "is_active", "token"]
        read_only_fields = ["created_by", "created_at", "revoked_at", "uses", "last_used_at"]
        extra_kwargs = {"house": {"required": False, "allow_null": True}, "project": {"required": False, "allow_null": True}, "expires_at": {"required": False}}

    def validate(self, attrs):
        request = self.context["request"]
        house = attrs.get("house")
        project = attrs.get("project")
        if house and project:
            raise serializers.ValidationError("An invitation can target at most one of house or project.")
        group = house or project
        if group is not None and not group.members.filter(pk=request.user.pk).exists():
            raise serializers.ValidationError("You must be a member of the house or project you invite to.")
        return attrs

    def create(self, validated_data):
        request = self.context["request"]
        kwargs = {}
        if "expires_at" in validated_data:
            kwargs["expires_at"] = validated_data["expires_at"]
        invitation, plaintext_token = Invitation.issue(house=validated_data.get("house"), project=validated_data.get("project"), created_by=request.user, label=validated_data.get("label", ""), **kwargs)
        invitation.token = plaintext_token
        return invitation


class InvitationRedeemSerializer(serializers.Serializer):
    token = serializers.CharField(write_only=True)
    username = serializers.CharField(required=False)
    password = serializers.CharField(required=False, write_only=True, style={"input_type": "password"})
    email = serializers.EmailField(required=False, allow_blank=True)

    def validate(self, attrs):
        invitation = Invitation.resolve(attrs["token"])
        if invitation is None:
            raise serializers.ValidationError({"token": "Invalid, expired or revoked invitation."})
        attrs["invitation"] = invitation
        request = self.context["request"]
        if request.user and request.user.is_authenticated:
            attrs["user"] = request.user
            attrs["created"] = False
            return attrs
        username = (attrs.get("username") or "").strip()
        password = attrs.get("password") or ""
        if not username or not password:
            raise serializers.ValidationError("Provide username and password to redeem without being logged in.")
        if User.objects.filter(username__iexact=username).exists():
            raise serializers.ValidationError({"username": "That username is taken."})
        try:
            validate_password(password)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": list(exc.messages)})
        attrs["username"] = username
        attrs["created"] = True
        return attrs

    def save(self):
        invitation = self.validated_data["invitation"]
        created = self.validated_data["created"]
        if created:
            user = User.objects.create_user(username=self.validated_data["username"], password=self.validated_data["password"], email=self.validated_data.get("email", ""))
        else:
            user = self.validated_data["user"]
        invitation.redeem(user)
        return user, invitation, created
