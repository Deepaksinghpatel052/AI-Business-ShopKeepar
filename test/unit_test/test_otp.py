from utils.otp import generate_otp, hash_otp, verify_otp


def test_generate_otp_default_length_is_6_digits():
    """generate_otp() with no arguments returns a 6-character all-digit string."""
    code = generate_otp()
    assert len(code) == 6
    assert code.isdigit()


def test_generate_otp_custom_length():
    """generate_otp(length=N) returns a code of exactly N digits."""
    code = generate_otp(length=4)
    assert len(code) == 4
    assert code.isdigit()


def test_generate_otp_is_not_constant():
    """Repeated calls to generate_otp() produce varying codes, not a fixed value."""
    codes = {generate_otp() for _ in range(20)}
    # Extremely unlikely all 20 random 6-digit codes collide.
    assert len(codes) > 1


def test_hash_otp_produces_verifiable_hash():
    """hash_otp() produces a hash (not the plaintext) that verify_otp() accepts for the same code."""
    code = "123456"
    hashed = hash_otp(code)
    assert hashed != code
    assert verify_otp(code, hashed) is True


def test_verify_otp_rejects_wrong_code():
    """verify_otp() returns False when the submitted code doesn't match the stored hash."""
    hashed = hash_otp("123456")
    assert verify_otp("654321", hashed) is False


def test_hash_otp_is_salted_and_differs_per_call():
    """hash_otp() returns a different hash each call for the same code, but both still verify."""
    code = "111111"
    hash_a = hash_otp(code)
    hash_b = hash_otp(code)
    assert hash_a != hash_b
    # Both still verify correctly against the same plaintext.
    assert verify_otp(code, hash_a) is True
    assert verify_otp(code, hash_b) is True
