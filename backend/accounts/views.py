import random
from datetime import timedelta

from django.contrib.auth.models import User
from django.utils import timezone

from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView


from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.permissions import IsAuthenticated


from .models import OTPVerification, UserProfile
from .serializers import UserSerializer


def generate_otp():
    return str(random.randint(100000, 999999))


def get_tokens_for_user(user):
    refresh = RefreshToken.for_user(user)

    return {
        "refresh": str(refresh),
        "access": str(refresh.access_token),
    }


class RegisterView(APIView):

    permission_classes = [AllowAny]

    def post(self, request):

        username = request.data.get("username")
        email = request.data.get("email")
        password = request.data.get("password")

        if not username or not password:
            return Response(
                {
                    "message": "Username and password are required."
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        if User.objects.filter(username=username).exists():
            return Response(
                {
                    "message": "Username already exists."
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        if email and User.objects.filter(email=email).exists():
            return Response(
                {
                    "message": "Email already exists."
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        user = User.objects.create_user(
            username=username,
            email=email,
            password=password
        )

        return Response(
            {
                "message": "Registration successful.",
                "user": UserSerializer(user).data
            },
            status=status.HTTP_201_CREATED
        )


class SendOTPView(APIView):

    permission_classes = [AllowAny]

    def post(self, request):

        phone = request.data.get("phone")
        purpose = request.data.get("purpose", "login")

        if not phone:
            return Response(
                {
                    "message": "Phone number is required."
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        phone = phone.strip()

        if not phone.isdigit():
            return Response(
                {
                    "message": "Phone number must contain only digits."
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        if len(phone) != 10:
            return Response(
                {
                    "message": "Enter a valid 10-digit phone number."
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        if purpose not in [
            "login",
            "registration",
            "password_reset"
        ]:
            return Response(
                {
                    "message": "Invalid OTP purpose."
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        OTPVerification.objects.filter(
            phone=phone,
            purpose=purpose,
            is_verified=False
        ).delete()

        otp = generate_otp()

        expires_at = timezone.now() + timedelta(minutes=5)

        OTPVerification.objects.create(
            phone=phone,
            otp=otp,
            purpose=purpose,
            expires_at=expires_at
        )

        # Development only
        print("=" * 50)
        print(f"OTP for {phone}: {otp}")
        print("=" * 50)

        return Response(
            {
                "message": "OTP sent successfully.",
                "expires_in": 300
            },
            status=status.HTTP_200_OK
        )


class VerifyOTPView(APIView):

    permission_classes = [AllowAny]

    def post(self, request):

        phone = request.data.get("phone")
        otp = request.data.get("otp")
        purpose = request.data.get("purpose", "login")

        if not phone or not otp:
            return Response(
                {
                    "message": "Phone number and OTP are required."
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        phone = phone.strip()
        otp = str(otp).strip()

        try:

            otp_record = OTPVerification.objects.filter(
                phone=phone,
                purpose=purpose,
                is_verified=False
            ).latest("created_at")

        except OTPVerification.DoesNotExist:

            return Response(
                {
                    "message": "OTP not found or already used."
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        if timezone.now() > otp_record.expires_at:

            return Response(
                {
                    "message": "OTP has expired. Please request a new OTP."
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        if otp_record.attempts >= 5:

            return Response(
                {
                    "message": "Too many incorrect attempts. Please request a new OTP."
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        if otp_record.otp != otp:

            otp_record.attempts += 1

            otp_record.save(
                update_fields=["attempts"]
            )

            return Response(
                {
                    "message": "Invalid OTP."
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        # OTP verified
        otp_record.is_verified = True

        otp_record.save(
            update_fields=["is_verified"]
        )

        # Find existing profile
        profile = UserProfile.objects.filter(
            phone=phone
        ).select_related("user").first()

        if profile:

            user = profile.user

        else:

            # Create new student
            username = f"user_{phone}"

            # Safety check
            if User.objects.filter(username=username).exists():
                username = f"user_{phone}_{random.randint(1000, 9999)}"

            user = User.objects.create_user(
                username=username
            )

            profile = UserProfile.objects.get(
                user=user
            )

            profile.phone = phone
            profile.role = "student"
            profile.is_phone_verified = True

            profile.save()

        # Mark phone verified
        profile.is_phone_verified = True

        profile.save(
            update_fields=["is_phone_verified"]
        )

        # Generate JWT
        tokens = get_tokens_for_user(user)

        return Response(
            {
                "message": "OTP verified successfully.",

                "tokens": {
                    "access": tokens["access"],
                    "refresh": tokens["refresh"]
                },

                "user": {
                    "id": user.id,
                    "username": user.username,
                    "phone": profile.phone,
                    "role": profile.role
                }
            },

            status=status.HTTP_200_OK
        )



class LoginView(APIView):

    permission_classes = [AllowAny]

    def post(self, request):

        username = request.data.get("username")
        password = request.data.get("password")

        if not username or not password:
            return Response(
                {
                    "message": "Username and password are required."
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        from django.contrib.auth import authenticate

        user = authenticate(
            username=username,
            password=password
        )

        if user is None:

            return Response(
                {
                    "message": "Invalid username or password."
                },
                status=status.HTTP_401_UNAUTHORIZED
            )

        if not user.is_active:

            return Response(
                {
                    "message": "This account is inactive."
                },
                status=status.HTTP_403_FORBIDDEN
            )

        tokens = get_tokens_for_user(user)

        profile = UserProfile.objects.filter(
            user=user
        ).first()

        return Response(
            {
                "message": "Login successful.",

                "tokens": {
                    "access": tokens["access"],
                    "refresh": tokens["refresh"]
                },

                "user": {
                    "id": user.id,
                    "username": user.username,
                    "email": user.email,
                    "phone": profile.phone if profile else None,
                    "role": profile.role if profile else "student"
                }
            },

            status=status.HTTP_200_OK
        )




class CurrentUserView(APIView):

    permission_classes = [IsAuthenticated]

    def get(self, request):

        user = request.user

        profile = UserProfile.objects.filter(
            user=user
        ).first()

        return Response(
            {
                "user": {
                    "id": user.id,
                    "username": user.username,
                    "email": user.email,
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "phone": profile.phone if profile else None,
                    "role": profile.role if profile else "student",
                    "is_phone_verified": (
                        profile.is_phone_verified
                        if profile
                        else False
                    ),
                }
            },

            status=status.HTTP_200_OK
        )



class StudentProfileSetupView(APIView):

    permission_classes = [IsAuthenticated]

    def post(self, request):

        user = request.user

        name = request.data.get("name")
        interest = request.data.get("interest")

        if not name:
            return Response(
                {
                    "message": "Name is required."
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        if interest not in [
            "government",
            "technology",
            "both"
        ]:
            return Response(
                {
                    "message": "Invalid interest selection."
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        profile = UserProfile.objects.get(
            user=user
        )

        name_parts = name.strip().split(" ", 1)

        user.first_name = name_parts[0]

        if len(name_parts) > 1:
            user.last_name = name_parts[1]

        user.save(
            update_fields=[
                "first_name",
                "last_name"
            ]
        )

        profile.interest = interest

        profile.save(
            update_fields=[
                "interest"
            ]
        )

        return Response(
            {
                "message": "Profile setup completed.",

                "user": {
                    "id": user.id,
                    "name": name,
                    "phone": profile.phone,
                    "role": profile.role,
                    "interest": profile.interest
                }
            },

            status=status.HTTP_200_OK
        )