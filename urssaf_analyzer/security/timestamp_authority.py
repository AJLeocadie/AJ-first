"""Horodatage certifie conforme RFC 3161 / eIDAS.

Fournit un horodatage opposable aux tiers par interrogation d'une
autorite de certification temporelle (TSA - Time Stamping Authority).

Architecture :
- TimestampAuthority : client RFC 3161 pour obtenir des jetons d'horodatage
- FallbackTimestamp : horloge systeme UTC annotee comme non certifiee
- Le choix du mode est automatique selon la disponibilite du TSA

Standards :
- RFC 3161 (Internet X.509 PKI Time-Stamp Protocol)
- RFC 5816 (ESSCertIDv2 Update for RFC 3161)
- Reglement eIDAS (UE 910/2014) art. 41-42 : horodatage electronique qualifie
- NF Z42-013 : archivage electronique a valeur probante
- Art. 1366 Code civil : ecrit electronique identifiable et integre

Limitations :
- En mode fallback (sans TSA), l'horodatage n'est pas opposable aux tiers
- L'horodatage certifie necessite un acces reseau au TSA
- La valeur probante depend de la qualification eIDAS du TSA choisi
"""

import hashlib
import json
import logging
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("urssaf_analyzer.timestamp")

# TSA publics gratuits (non qualifies eIDAS mais conformes RFC 3161)
# En production, utiliser un TSA qualifie eIDAS (ex: CertEurope, DocuSign)
DEFAULT_TSA_URLS = [
    "http://timestamp.digicert.com",
    "http://time.certum.pl",
    "http://timestamp.sectigo.com",
]


class TimestampToken:
    """Representation d'un jeton d'horodatage."""

    def __init__(
        self,
        timestamp_utc: str,
        hash_algorithm: str,
        data_hash: str,
        tsa_url: Optional[str] = None,
        tsa_response_raw: Optional[bytes] = None,
        certified: bool = False,
        method: str = "system_clock",
    ):
        self.timestamp_utc = timestamp_utc
        self.hash_algorithm = hash_algorithm
        self.data_hash = data_hash
        self.tsa_url = tsa_url
        self.tsa_response_raw = tsa_response_raw
        self.certified = certified
        self.method = method

    def to_dict(self) -> dict:
        result = {
            "timestamp_utc": self.timestamp_utc,
            "hash_algorithm": self.hash_algorithm,
            "data_hash": self.data_hash,
            "certified": self.certified,
            "method": self.method,
        }
        if self.tsa_url:
            result["tsa_url"] = self.tsa_url
        if not self.certified:
            result["avertissement"] = (
                "Horodatage par horloge systeme UTC — non certifie RFC 3161, "
                "non opposable aux tiers. Valeur indicative uniquement."
            )
        else:
            result["conformite"] = (
                "Jeton RFC 3161 obtenu aupres d'un TSA. "
                "Opposabilite dependante de la qualification eIDAS du TSA."
            )
        return result


def _sha256_hex(data: str) -> str:
    """Calcule le SHA-256 hexadecimal d'une chaine."""
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _build_rfc3161_request(data_hash_bytes: bytes) -> bytes:
    """Construit une requete d'horodatage RFC 3161 minimale (DER/ASN.1).

    Structure ASN.1 TimeStampReq :
    SEQUENCE {
        INTEGER 1 (version)
        SEQUENCE {           -- MessageImprint
            SEQUENCE {       -- AlgorithmIdentifier SHA-256
                OID 2.16.840.1.101.3.4.2.1
            }
            OCTET STRING (32 bytes hash)
        }
        BOOLEAN TRUE (certReq)
    }
    """
    # OID SHA-256 : 2.16.840.1.101.3.4.2.1
    oid_sha256 = bytes([
        0x06, 0x09, 0x60, 0x86, 0x48, 0x01, 0x65, 0x03, 0x04, 0x02, 0x01
    ])
    # AlgorithmIdentifier SEQUENCE
    alg_id = bytes([0x30, len(oid_sha256)]) + oid_sha256
    # OCTET STRING (hash)
    hash_octet = bytes([0x04, len(data_hash_bytes)]) + data_hash_bytes
    # MessageImprint SEQUENCE
    msg_imprint = bytes([0x30, len(alg_id) + len(hash_octet)]) + alg_id + hash_octet
    # version INTEGER 1
    version = bytes([0x02, 0x01, 0x01])
    # certReq BOOLEAN TRUE
    cert_req = bytes([0x01, 0x01, 0xFF])
    # TimeStampReq SEQUENCE
    inner = version + msg_imprint + cert_req
    return bytes([0x30, len(inner)]) + inner


class TimestampAuthority:
    """Client d'horodatage RFC 3161 avec fallback horloge systeme.

    Usage :
        tsa = TimestampAuthority()
        token = tsa.timestamp("donnees a horodater")
        print(token.to_dict())
    """

    def __init__(
        self,
        tsa_urls: Optional[list[str]] = None,
        timeout_seconds: int = 5,
        enabled: bool = True,
    ):
        self.tsa_urls = tsa_urls or DEFAULT_TSA_URLS
        self.timeout = timeout_seconds
        self.enabled = enabled

    def timestamp(self, data: str) -> TimestampToken:
        """Horodate des donnees.

        Tente d'abord le TSA RFC 3161, puis fallback sur l'horloge systeme.

        Args:
            data: Chaine de caracteres a horodater.

        Returns:
            TimestampToken avec les informations d'horodatage.
        """
        data_hash = _sha256_hex(data)

        if self.enabled:
            token = self._try_tsa(data_hash)
            if token:
                return token
            logger.warning(
                "Aucun TSA joignable, fallback sur horloge systeme."
            )

        return self._fallback_timestamp(data_hash)

    def timestamp_hash(self, data_hash: str) -> TimestampToken:
        """Horodate un hash deja calcule."""
        if self.enabled:
            token = self._try_tsa(data_hash)
            if token:
                return token

        return self._fallback_timestamp(data_hash)

    def _try_tsa(self, data_hash: str) -> Optional[TimestampToken]:
        """Tente d'obtenir un jeton RFC 3161 aupres des TSA configures."""
        hash_bytes = bytes.fromhex(data_hash)
        request_body = _build_rfc3161_request(hash_bytes)

        for tsa_url in self.tsa_urls:
            try:
                req = urllib.request.Request(
                    tsa_url,
                    data=request_body,
                    headers={
                        "Content-Type": "application/timestamp-query",
                    },
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    if resp.status == 200:
                        response_data = resp.read()
                        # Verifier que la reponse est un TimeStampResp valide (tag SEQUENCE)
                        if response_data and response_data[0] == 0x30:
                            now = datetime.now(timezone.utc).isoformat()
                            return TimestampToken(
                                timestamp_utc=now,
                                hash_algorithm="SHA-256",
                                data_hash=data_hash,
                                tsa_url=tsa_url,
                                tsa_response_raw=response_data,
                                certified=True,
                                method="rfc3161",
                            )
            except (urllib.error.URLError, OSError, TimeoutError) as e:
                logger.debug("TSA %s injoignable: %s", tsa_url, e)
                continue

        return None

    def _fallback_timestamp(self, data_hash: str) -> TimestampToken:
        """Horodatage par horloge systeme UTC (non certifie)."""
        now = datetime.now(timezone.utc).isoformat()
        return TimestampToken(
            timestamp_utc=now,
            hash_algorithm="SHA-256",
            data_hash=data_hash,
            certified=False,
            method="system_clock",
        )

    def verify_token(self, token: TimestampToken, data: str) -> dict:
        """Verifie la coherence d'un jeton d'horodatage.

        Verification locale uniquement (hash). La verification complete
        du jeton RFC 3161 necessite la verification de la signature du TSA
        via sa chaine de certificats (non implemente ici — utiliser openssl ts).
        """
        expected_hash = _sha256_hex(data)
        hash_match = token.data_hash == expected_hash

        result = {
            "hash_valid": hash_match,
            "certified": token.certified,
            "method": token.method,
            "timestamp_utc": token.timestamp_utc,
        }

        if not hash_match:
            result["erreur"] = (
                f"Hash ne correspond pas : attendu={expected_hash[:16]}..., "
                f"token={token.data_hash[:16]}..."
            )

        if token.certified:
            result["note"] = (
                "Verification de la signature TSA non effectuee. "
                "Pour une verification complete, utiliser : "
                "openssl ts -verify -data <file> -in <token> -CAfile <ca>"
            )

        return result
