from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from verso.models import Booking, BookingRequest, CheckOut, House

User = get_user_model()


class BookingViewSetTests(APITestCase):
    def setUp(self):
        self.member = User.objects.create_user(username='member', password='x')
        self.outsider = User.objects.create_user(username='outsider', password='x')
        self.house = House.objects.create(name='Home')
        self.house.members.add(self.member)
        self.client = APIClient()
        self.client.force_authenticate(user=self.member)

    def test_member_can_create_a_booking_for_their_house(self):
        response = self.client.post(
            '/api/verso/bookings/',
            {'house': self.house.pk, 'visitor': 'Guest', 'start_date': '2026-01-01', 'end_date': '2026-01-03'},
        )

        self.assertEqual(response.status_code, 201)

    def test_non_member_cannot_create_a_booking_for_the_house(self):
        client = APIClient()
        client.force_authenticate(user=self.outsider)

        response = client.post(
            '/api/verso/bookings/',
            {'house': self.house.pk, 'visitor': 'Guest', 'start_date': '2026-01-01', 'end_date': '2026-01-03'},
        )

        self.assertEqual(response.status_code, 400)

    def test_outsider_cannot_see_the_house_bookings(self):
        Booking.objects.create(house=self.house, visitor='Guest', start_date='2026-01-01', end_date='2026-01-03')
        client = APIClient()
        client.force_authenticate(user=self.outsider)

        response = client.get('/api/verso/bookings/')

        self.assertEqual(response.data, [])

    def test_future_filter(self):
        today = timezone.localdate()
        past = Booking.objects.create(
            house=self.house, visitor='Past guest',
            start_date=today.replace(year=today.year - 1), end_date=today.replace(year=today.year - 1),
        )
        future = Booking.objects.create(
            house=self.house, visitor='Future guest',
            start_date=today.replace(year=today.year + 1), end_date=today.replace(year=today.year + 1),
        )

        response = self.client.get('/api/verso/bookings/', {'future': 'true'})

        ids = {row['id'] for row in response.data}
        self.assertEqual(ids, {future.pk})
        self.assertNotIn(past.pk, ids)

    def test_overlap_filter_returns_bookings_touching_the_range(self):
        before = Booking.objects.create(
            house=self.house, visitor='Before', start_date='2026-01-01', end_date='2026-01-03',
        )
        spanning = Booking.objects.create(
            house=self.house, visitor='Spanning', start_date='2026-01-28', end_date='2026-02-03',
        )
        inside = Booking.objects.create(
            house=self.house, visitor='Inside', start_date='2026-02-10', end_date='2026-02-12',
        )
        after = Booking.objects.create(
            house=self.house, visitor='After', start_date='2026-03-01', end_date='2026-03-02',
        )

        response = self.client.get(
            '/api/verso/bookings/',
            {'ends_on_or_after': '2026-02-01', 'starts_on_or_before': '2026-02-28'},
        )

        ids = {row['id'] for row in response.data}
        self.assertEqual(ids, {spanning.pk, inside.pk})
        self.assertNotIn(before.pk, ids)
        self.assertNotIn(after.pk, ids)


class BookingRequestViewSetTests(APITestCase):
    def setUp(self):
        self.member = User.objects.create_user(username='member', password='x')
        self.house = House.objects.create(name='Home')
        self.house.members.add(self.member)
        self.client = APIClient()
        self.client.force_authenticate(user=self.member)

    def test_member_can_create_a_booking_request(self):
        response = self.client.post(
            '/api/verso/booking-requests/',
            {'house': self.house.pk, 'requester': 'Someone', 'start_date': '2026-01-01', 'end_date': '2026-01-03'},
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['status'], 'pending')


class CheckOutViewSetTests(APITestCase):
    def setUp(self):
        self.member = User.objects.create_user(username='member', password='x')
        self.outsider = User.objects.create_user(username='outsider', password='x')
        self.house = House.objects.create(name='Home')
        self.house.members.add(self.member)
        self.booking = Booking.objects.create(
            house=self.house, visitor='Guest', start_date='2026-01-01', end_date='2026-01-03'
        )

    def test_member_can_check_out_a_booking(self):
        client = APIClient()
        client.force_authenticate(user=self.member)

        response = client.post('/api/verso/check-outs/', {'booking': self.booking.pk, 'notes': 'All good'})

        self.assertEqual(response.status_code, 201)

    def test_non_member_cannot_check_out_a_booking(self):
        client = APIClient()
        client.force_authenticate(user=self.outsider)

        response = client.post('/api/verso/check-outs/', {'booking': self.booking.pk, 'notes': 'All good'})

        self.assertEqual(response.status_code, 400)

    def test_house_query_param_scopes_the_list(self):
        CheckOut.objects.create(booking=self.booking, notes='first')
        other_house = House.objects.create(name='Other')
        other_house.members.add(self.member)
        other_booking = Booking.objects.create(
            house=other_house, visitor='Guest', start_date='2026-01-01', end_date='2026-01-03'
        )
        CheckOut.objects.create(booking=other_booking, notes='second')
        client = APIClient()
        client.force_authenticate(user=self.member)

        response = client.get('/api/verso/check-outs/', {'booking__house': self.house.pk})

        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['notes'], 'first')
