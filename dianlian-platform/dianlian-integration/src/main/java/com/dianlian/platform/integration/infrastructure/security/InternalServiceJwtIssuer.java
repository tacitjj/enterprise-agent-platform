package com.dianlian.platform.integration.infrastructure.security;

import com.nimbusds.jose.JOSEException;
import com.nimbusds.jose.JOSEObjectType;
import com.nimbusds.jose.JWSAlgorithm;
import com.nimbusds.jose.JWSHeader;
import com.nimbusds.jose.crypto.RSASSASigner;
import com.nimbusds.jose.jwk.JWK;
import com.nimbusds.jose.jwk.RSAKey;
import com.nimbusds.jwt.JWTClaimsSet;
import com.nimbusds.jwt.SignedJWT;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.interfaces.RSAPrivateKey;
import java.time.Clock;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.Arrays;
import java.util.Date;
import java.util.Objects;
import java.util.Set;
import java.util.UUID;
import java.util.stream.Collectors;

public final class InternalServiceJwtIssuer {

    public static final String ISSUER = "dianlian-platform";
    public static final String AUDIENCE = "dianlian-ai-runtime";
    public static final String SUBJECT = "dianlian-platform";
    public static final String TOKEN_USE_CLAIM = "token_use";
    public static final String TOKEN_USE_SERVICE = "service";
    public static final String SCOPE_CLAIM = "scope";

    private final RSASSASigner signer;
    private final String keyId;
    private final long ttlSeconds;
    private final Clock clock;

    InternalServiceJwtIssuer(
            RSAPrivateKey privateKey,
            String keyId,
            long ttlSeconds,
            Clock clock
    ) {
        this.signer = new RSASSASigner(Objects.requireNonNull(privateKey, "privateKey must not be null"));
        if (privateKey.getModulus().bitLength() < 2048) {
            throw new IllegalArgumentException("internal service JWT RSA key must be at least 2048 bits");
        }
        this.keyId = Objects.requireNonNull(keyId, "keyId must not be null");
        if (ttlSeconds < 1 || ttlSeconds > InternalServiceJwtProperties.MAX_TTL_SECONDS) {
            throw new IllegalArgumentException("internal service JWT ttlSeconds must be between 1 and 60");
        }
        this.ttlSeconds = ttlSeconds;
        this.clock = Objects.requireNonNull(clock, "clock must not be null");
    }

    static InternalServiceJwtIssuer from(InternalServiceJwtProperties properties) {
        Objects.requireNonNull(properties, "properties must not be null");
        try {
            var pem = Files.readString(Path.of(properties.privateKeyPath()), StandardCharsets.US_ASCII);
            var jwk = JWK.parseFromPEMEncodedObjects(pem);
            if (!(jwk instanceof RSAKey rsaKey) || !rsaKey.isPrivate()) {
                throw new IllegalStateException("internal service JWT key must be an RSA private key");
            }
            return new InternalServiceJwtIssuer(
                    rsaKey.toRSAPrivateKey(),
                    properties.keyId(),
                    properties.ttlSeconds(),
                    Clock.systemUTC()
            );
        } catch (IOException | JOSEException | RuntimeException exception) {
            throw new IllegalStateException("internal service JWT private key is unavailable or invalid");
        }
    }

    public IssuedInternalServiceJwt issue(InternalServiceJwtScope... requestedScopes) {
        if (requestedScopes == null || requestedScopes.length == 0) {
            throw new IllegalArgumentException("at least one internal service JWT scope is required");
        }
        if (Arrays.stream(requestedScopes).anyMatch(Objects::isNull)) {
            throw new IllegalArgumentException("internal service JWT scope must not be null");
        }
        Set<InternalServiceJwtScope> scopes = Set.copyOf(Arrays.asList(requestedScopes));

        Instant issuedAt = clock.instant().truncatedTo(ChronoUnit.SECONDS);
        Instant expiresAt = issuedAt.plusSeconds(ttlSeconds);
        var claims = new JWTClaimsSet.Builder()
                .issuer(ISSUER)
                .subject(SUBJECT)
                .audience(AUDIENCE)
                .issueTime(Date.from(issuedAt))
                .expirationTime(Date.from(expiresAt))
                .jwtID(UUID.randomUUID().toString())
                .claim(TOKEN_USE_CLAIM, TOKEN_USE_SERVICE)
                .claim(SCOPE_CLAIM, scopes.stream()
                        .map(InternalServiceJwtScope::value)
                        .sorted()
                        .collect(Collectors.joining(" ")))
                .build();
        var token = new SignedJWT(
                new JWSHeader.Builder(JWSAlgorithm.RS256)
                        .type(JOSEObjectType.JWT)
                        .keyID(keyId)
                        .build(),
                claims
        );
        try {
            token.sign(signer);
        } catch (JOSEException exception) {
            throw new IllegalStateException("internal service JWT signing failed", exception);
        }
        return new IssuedInternalServiceJwt(token.serialize(), issuedAt, expiresAt);
    }

    public record IssuedInternalServiceJwt(String value, Instant issuedAt, Instant expiresAt) {

        @Override
        public String toString() {
            return "IssuedInternalServiceJwt[value=<redacted>, issuedAt=" + issuedAt
                    + ", expiresAt=" + expiresAt + "]";
        }
    }
}
