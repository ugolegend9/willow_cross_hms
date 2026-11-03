from django.db import IntegrityError, models, transaction
from django.utils import timezone


class Patient(models.Model):
    class Gender(models.TextChoices):
        MALE = 'M', 'Male'
        FEMALE = 'F', 'Female'

    class BloodGroup(models.TextChoices):
        A_POS = 'A+', 'A+'
        A_NEG = 'A-', 'A-'
        B_POS = 'B+', 'B+'
        B_NEG = 'B-', 'B-'
        AB_POS = 'AB+', 'AB+'
        AB_NEG = 'AB-', 'AB-'
        O_POS = 'O+', 'O+'
        O_NEG = 'O-', 'O-'
        UNKNOWN = 'UNK', 'Unknown'

    mrn = models.CharField('MRN', max_length=20, unique=True, editable=False)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    date_of_birth = models.DateField()
    gender = models.CharField(max_length=1, choices=Gender.choices)
    blood_group = models.CharField(max_length=3, choices=BloodGroup.choices, default=BloodGroup.UNKNOWN)
    phone_number = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    registered_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-registered_at']

    def save(self, *args, **kwargs):
        if self.mrn:
            return super().save(*args, **kwargs)
        # Two front-desk staff can be handed the same "next" number at once.
        # The unique constraint stops the second one, so retry with a fresh
        # number instead of showing them an error page.
        for attempt in range(1, 6):
            self.mrn = self._generate_mrn()
            try:
                with transaction.atomic():
                    return super().save(*args, **kwargs)
            except IntegrityError:
                collided = Patient.objects.filter(mrn=self.mrn).exists()
                self.mrn = ''
                if not collided or attempt == 5:
                    raise

    def _generate_mrn(self):
        year = timezone.localdate().year  # local year: UTC is still last year for an hour after New Year in Lagos
        last = Patient.objects.filter(mrn__startswith=f"WCH-{year}-").order_by('-mrn').first()
        seq = int(last.mrn.split('-')[-1]) + 1 if last else 1
        return f"WCH-{year}-{seq:05d}"

    def __str__(self):
        return f"{self.full_name} ({self.mrn})"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"


class NextOfKin(models.Model):
    class Meta:
        verbose_name = 'next of kin'
        verbose_name_plural = 'next of kin'

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name='next_of_kin')
    full_name = models.CharField(max_length=150)
    relationship = models.CharField(max_length=50)
    phone_number = models.CharField(max_length=20)

    def __str__(self):
        return f"{self.full_name} ({self.relationship} of {self.patient.full_name})"


class InsurancePolicy(models.Model):
    class Meta:
        verbose_name_plural = 'insurance policies'

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name='insurance_policies')
    provider_name = models.CharField(max_length=150)
    policy_number = models.CharField(max_length=100)
    valid_until = models.DateField(null=True, blank=True)

    def __str__(self):
        return f"{self.provider_name} — {self.policy_number}"
