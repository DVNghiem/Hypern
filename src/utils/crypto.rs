use pyo3::prelude::*;
use rand::{Rng, RngExt};

// ──────────────────────── random / token generators ──────────────────────── //

/// Generate a cryptographically-secure random URL-safe token string.
///
/// Use for API keys, password-reset links, CSRF tokens, etc.
///
/// Example (Python):
///     from hypern._hypern import random_token
///     token = random_token(48)   # "j7Kx3mQpZw..."
#[pyfunction]
#[pyo3(signature = (length=32))]
pub fn random_token(length: usize) -> String {
    const ALPHABET: &[u8] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
    let mut rng = rand::rng();
    (0..length)
        .map(|_| {
            let idx = rng.random_range(0..ALPHABET.len());
            ALPHABET[idx] as char
        })
        .collect()
}

/// Generate **n** cryptographically-secure random bytes.
///
/// Example (Python):
///     raw = random_bytes(16)
///     assert isinstance(raw, bytes) and len(raw) == 16
#[pyfunction]
pub fn random_bytes(n: usize) -> Vec<u8> {
    let mut buf = vec![0u8; n];
    rand::rng().fill_bytes(&mut buf);
    buf
}

// ──────────────────────────── HMAC / hashing ─────────────────────────────── //

/// Compute HMAC-SHA-256 and return the **hex** digest.
///
/// Common use-case: verifying Stripe / GitHub / Slack webhook signatures.
///
/// Example (Python):
///     sig = hmac_sha256_hex("my_secret", body_text)
#[pyfunction]
pub fn hmac_sha256_hex(key: &str, data: &str) -> String {
    use hmac::{Hmac, Mac};
    use sha2::Sha256;
    type HmacSha256 = Hmac<Sha256>;

    let mut mac = HmacSha256::new_from_slice(key.as_bytes()).expect("HMAC: any key size");
    mac.update(data.as_bytes());
    hex_encode(&mac.finalize().into_bytes())
}

/// Compute HMAC-SHA-256 from raw byte inputs and return raw bytes.
#[pyfunction]
pub fn hmac_sha256_bytes(key: &[u8], data: &[u8]) -> Vec<u8> {
    use hmac::{Hmac, Mac};
    use sha2::Sha256;
    type HmacSha256 = Hmac<Sha256>;

    let mut mac = HmacSha256::new_from_slice(key).expect("HMAC: any key size");
    mac.update(data);
    mac.finalize().into_bytes().to_vec()
}

/// Compute SHA-256 hex digest of a string.
///
/// Example (Python):
///     sha256_hex("hello")
///     # "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
#[pyfunction]
pub fn sha256_hex(data: &str) -> String {
    use sha2::{Digest, Sha256};
    let mut h = Sha256::new();
    h.update(data.as_bytes());
    hex_encode(&h.finalize())
}

/// Constant-time comparison of two byte strings (timing-attack safe).
///
/// Returns ``True`` only when both length and content match.
///
/// Example (Python):
///     if secure_compare(received_sig, expected_sig): ...
#[pyfunction]
pub fn secure_compare(a: &[u8], b: &[u8]) -> bool {
    if a.len() != b.len() {
        return false;
    }
    let mut acc = 0u8;
    for (x, y) in a.iter().zip(b.iter()) {
        acc |= x ^ y;
    }
    acc == 0
}

// ─────────────────────────── Base-64 helpers ─────────────────────────────── //

/// Encode bytes to standard Base64.
///
/// Example (Python):
///     b64_encode(b"hello") == "aGVsbG8="
#[pyfunction]
pub fn b64_encode(data: &[u8]) -> String {
    use base64::Engine;
    base64::engine::general_purpose::STANDARD.encode(data)
}

/// Decode a standard Base64 string.  Returns ``None`` on invalid input.
#[pyfunction]
pub fn b64_decode(data: &str) -> Option<Vec<u8>> {
    use base64::Engine;
    base64::engine::general_purpose::STANDARD.decode(data).ok()
}

/// Encode bytes to URL-safe Base64 (no padding).
#[pyfunction]
pub fn b64url_encode(data: &[u8]) -> String {
    use base64::Engine;
    base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(data)
}

/// Decode a URL-safe Base64 string (no padding).  Returns ``None`` on invalid
/// input.
#[pyfunction]
pub fn b64url_decode(data: &str) -> Option<Vec<u8>> {
    use base64::Engine;
    base64::engine::general_purpose::URL_SAFE_NO_PAD
        .decode(data)
        .ok()
}

// ──────────────────────────── UUID generators ────────────────────────────── //

/// Generate a UUID v4 (random) as a string.
#[pyfunction]
pub fn uuid_v4() -> String {
    uuid::Uuid::new_v4().to_string()
}

/// Generate a UUID v7 (time-sorted) as a string.
///
/// Ideal for database primary keys — lexicographic order = insertion order.
#[pyfunction]
pub fn uuid_v7() -> String {
    uuid::Uuid::now_v7().to_string()
}

// ────────────────────────────── xxhash fast ──────────────────────────────── //

/// Compute xxHash3-64 of a string and return the ``u64`` hash.
///
/// Useful for Bloom filters, deduplication, cache keys, etc.
///
/// Example (Python):
///     h = fast_hash("some-cache-key")
#[pyfunction]
pub fn fast_hash(data: &str) -> u64 {
    xxhash_rust::xxh3::xxh3_64(data.as_bytes())
}

/// Compute xxHash3-64 of raw bytes and return the ``u64`` hash.
#[pyfunction]
pub fn fast_hash_bytes(data: &[u8]) -> u64 {
    xxhash_rust::xxh3::xxh3_64(data)
}

// ─────────────────────────── JWT RS256 / ES256 ───────────────────────────── //

/// Sign a JWT payload with RS256 (RSA PKCS#1 v1.5 + SHA-256).
///
/// Args:
///     payload_json: A JSON-encoded string of the JWT claims.
///     pem_key: The PEM-encoded RSA **private** key.
///
/// Returns the compact JWS string ``header.payload.signature``.
#[pyfunction]
pub fn jwt_sign_rs256(payload_json: &str, pem_key: &[u8]) -> PyResult<String> {
    use base64::Engine;
    use rsa::pkcs8::DecodePrivateKey;
    use rsa::pkcs1v15::SigningKey;
    use sha2::Sha256;
    use signature::SignatureEncoding;

    let header = r#"{"alg":"RS256","typ":"JWT"}"#;
    let b64url = base64::engine::general_purpose::URL_SAFE_NO_PAD;

    let header_b64 = b64url.encode(header.as_bytes());
    let payload_b64 = b64url.encode(payload_json.as_bytes());
    let signing_input = format!("{}.{}", header_b64, payload_b64);

    let pem_str = std::str::from_utf8(pem_key)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("Invalid PEM encoding: {}", e)))?;

    let private_key = rsa::RsaPrivateKey::from_pkcs8_pem(pem_str)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("Invalid RSA private key: {}", e)))?;

    let signing_key = SigningKey::<Sha256>::new_unprefixed(private_key);
    let sig: rsa::pkcs1v15::Signature = signature::Signer::sign(&signing_key, signing_input.as_bytes());

    let sig_b64 = b64url.encode(sig.to_bytes());
    Ok(format!("{}.{}", signing_input, sig_b64))
}

/// Verify a JWT token signed with RS256 and return the payload JSON.
///
/// Args:
///     token: The compact JWS string.
///     pem_key: The PEM-encoded RSA **public** key.
///
/// Returns the decoded payload JSON string.
#[pyfunction]
pub fn jwt_verify_rs256(token: &str, pem_key: &[u8]) -> PyResult<String> {
    use base64::Engine;
    use rsa::pkcs8::DecodePublicKey;
    use rsa::pkcs1v15::VerifyingKey;
    use sha2::Sha256;
    use signature::Verifier;

    let b64url = base64::engine::general_purpose::URL_SAFE_NO_PAD;

    let parts: Vec<&str> = token.splitn(3, '.').collect();
    if parts.len() != 3 {
        return Err(pyo3::exceptions::PyValueError::new_err("Invalid JWT format"));
    }

    let signing_input = format!("{}.{}", parts[0], parts[1]);

    let pem_str = std::str::from_utf8(pem_key)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("Invalid PEM encoding: {}", e)))?;

    let public_key = rsa::RsaPublicKey::from_public_key_pem(pem_str)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("Invalid RSA public key: {}", e)))?;

    let verifying_key = VerifyingKey::<Sha256>::new_unprefixed(public_key);
    let sig_bytes = b64url.decode(parts[2])
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("Invalid signature encoding: {}", e)))?;

    let signature = rsa::pkcs1v15::Signature::try_from(sig_bytes.as_slice())
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("Invalid signature: {}", e)))?;

    verifying_key.verify(signing_input.as_bytes(), &signature)
        .map_err(|_| pyo3::exceptions::PyValueError::new_err("JWT signature verification failed"))?;

    let payload_bytes = b64url.decode(parts[1])
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("Invalid payload encoding: {}", e)))?;

    String::from_utf8(payload_bytes)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("Invalid payload UTF-8: {}", e)))
}

/// Sign a JWT payload with ES256 (ECDSA P-256 + SHA-256).
///
/// Args:
///     payload_json: A JSON-encoded string of the JWT claims.
///     pem_key: The PEM-encoded EC **private** key (PKCS#8 or SEC1).
///
/// Returns the compact JWS string ``header.payload.signature``.
#[pyfunction]
pub fn jwt_sign_es256(payload_json: &str, pem_key: &[u8]) -> PyResult<String> {
    use base64::Engine;
    use p256::ecdsa::{SigningKey as EcSigningKey, Signature as EcSignature};
    use p256::pkcs8::DecodePrivateKey;

    let header = r#"{"alg":"ES256","typ":"JWT"}"#;
    let b64url = base64::engine::general_purpose::URL_SAFE_NO_PAD;

    let header_b64 = b64url.encode(header.as_bytes());
    let payload_b64 = b64url.encode(payload_json.as_bytes());
    let signing_input = format!("{}.{}", header_b64, payload_b64);

    let pem_str = std::str::from_utf8(pem_key)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("Invalid PEM encoding: {}", e)))?;

    let sk = EcSigningKey::from_pkcs8_pem(pem_str)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("Invalid EC private key: {}", e)))?;

    let sig: EcSignature = signature::Signer::sign(&sk, signing_input.as_bytes());
    let sig_b64 = b64url.encode(sig.to_bytes());

    Ok(format!("{}.{}", signing_input, sig_b64))
}

/// Verify a JWT token signed with ES256 and return the payload JSON.
///
/// Args:
///     token: The compact JWS string.
///     pem_key: The PEM-encoded EC **public** key.
///
/// Returns the decoded payload JSON string.
#[pyfunction]
pub fn jwt_verify_es256(token: &str, pem_key: &[u8]) -> PyResult<String> {
    use base64::Engine;
    use p256::ecdsa::{VerifyingKey as EcVerifyingKey, Signature as EcSignature};
    use p256::pkcs8::DecodePublicKey;
    use signature::Verifier;

    let b64url = base64::engine::general_purpose::URL_SAFE_NO_PAD;

    let parts: Vec<&str> = token.splitn(3, '.').collect();
    if parts.len() != 3 {
        return Err(pyo3::exceptions::PyValueError::new_err("Invalid JWT format"));
    }

    let signing_input = format!("{}.{}", parts[0], parts[1]);

    let pem_str = std::str::from_utf8(pem_key)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("Invalid PEM encoding: {}", e)))?;

    let vk = EcVerifyingKey::from_public_key_pem(pem_str)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("Invalid EC public key: {}", e)))?;

    let sig_bytes = b64url.decode(parts[2])
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("Invalid signature encoding: {}", e)))?;

    let sig = EcSignature::from_slice(&sig_bytes)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("Invalid signature: {}", e)))?;

    vk.verify(signing_input.as_bytes(), &sig)
        .map_err(|_| pyo3::exceptions::PyValueError::new_err("JWT signature verification failed"))?;

    let payload_bytes = b64url.decode(parts[1])
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("Invalid payload encoding: {}", e)))?;

    String::from_utf8(payload_bytes)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("Invalid payload UTF-8: {}", e)))
}

// ───────────────────────── internal helpers ──────────────────────────────── //

#[inline]
fn hex_encode(bytes: &[u8]) -> String {
    bytes.iter().fold(
        String::with_capacity(bytes.len() * 2),
        |mut s, b| {
            use std::fmt::Write;
            let _ = write!(s, "{:02x}", b);
            s
        },
    )
}

// ──────────────────── module registration ────────────────────────────────── //

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(random_token, m)?)?;
    m.add_function(wrap_pyfunction!(random_bytes, m)?)?;
    m.add_function(wrap_pyfunction!(hmac_sha256_hex, m)?)?;
    m.add_function(wrap_pyfunction!(hmac_sha256_bytes, m)?)?;
    m.add_function(wrap_pyfunction!(sha256_hex, m)?)?;
    m.add_function(wrap_pyfunction!(secure_compare, m)?)?;
    m.add_function(wrap_pyfunction!(b64_encode, m)?)?;
    m.add_function(wrap_pyfunction!(b64_decode, m)?)?;
    m.add_function(wrap_pyfunction!(b64url_encode, m)?)?;
    m.add_function(wrap_pyfunction!(b64url_decode, m)?)?;
    m.add_function(wrap_pyfunction!(uuid_v4, m)?)?;
    m.add_function(wrap_pyfunction!(uuid_v7, m)?)?;
    m.add_function(wrap_pyfunction!(fast_hash, m)?)?;
    m.add_function(wrap_pyfunction!(fast_hash_bytes, m)?)?;
    m.add_function(wrap_pyfunction!(jwt_sign_rs256, m)?)?;
    m.add_function(wrap_pyfunction!(jwt_verify_rs256, m)?)?;
    m.add_function(wrap_pyfunction!(jwt_sign_es256, m)?)?;
    m.add_function(wrap_pyfunction!(jwt_verify_es256, m)?)?;
    Ok(())
}
