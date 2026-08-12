package com.dianlian.platform.integration.infrastructure.security;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.nimbusds.jose.crypto.RSASSAVerifier;
import com.nimbusds.jwt.SignedJWT;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.KeyPair;
import java.security.KeyPairGenerator;
import java.security.interfaces.RSAPrivateKey;
import java.security.interfaces.RSAPublicKey;
import java.time.Duration;
import java.util.Base64;
import java.util.Set;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;

class InternalServiceJwtIssuerTests {

    @TempDir
    Path temporaryDirectory;

    @Test
    void issuesShortLivedRs256TokenWithDedicatedServiceClaims() throws Exception {
        KeyPair keyPair = rsaKeyPair(2048);
        Path privateKeyPath = writePkcs8Pem((RSAPrivateKey) keyPair.getPrivate());
        var issuer = InternalServiceJwtIssuer.from(new InternalServiceJwtProperties(
                true,
                "service-2026-08",
                privateKeyPath.toString(),
                30
        ));

        var issued = issuer.issue(
                InternalServiceJwtScope.CONTEXT_INDEX_WRITE,
                InternalServiceJwtScope.CONTEXT_RETRIEVE
        );
        var parsed = SignedJWT.parse(issued.value());

        assertThat(parsed.getHeader().getAlgorithm().getName()).isEqualTo("RS256");
        assertThat(parsed.getHeader().getKeyID()).isEqualTo("service-2026-08");
        assertThat(parsed.verify(new RSASSAVerifier((RSAPublicKey) keyPair.getPublic()))).isTrue();
        assertThat(parsed.getJWTClaimsSet().getIssuer()).isEqualTo(InternalServiceJwtIssuer.ISSUER);
        assertThat(parsed.getJWTClaimsSet().getAudience()).containsExactly(InternalServiceJwtIssuer.AUDIENCE);
        assertThat(parsed.getJWTClaimsSet().getSubject()).isEqualTo(InternalServiceJwtIssuer.SUBJECT);
        assertThat(parsed.getJWTClaimsSet().getStringClaim(InternalServiceJwtIssuer.TOKEN_USE_CLAIM))
                .isEqualTo(InternalServiceJwtIssuer.TOKEN_USE_SERVICE);
        assertThat(Set.of(parsed.getJWTClaimsSet()
                .getStringClaim(InternalServiceJwtIssuer.SCOPE_CLAIM)
                .split(" ")))
                .containsExactlyInAnyOrder("context.index.write", "context.retrieve");
        assertThat(Duration.between(issued.issuedAt(), issued.expiresAt()))
                .isEqualTo(Duration.ofSeconds(30));
        assertThat(UUID.fromString(parsed.getJWTClaimsSet().getJWTID())).isNotNull();
        assertThat(issued.toString()).contains("value=<redacted>").doesNotContain(issued.value());
        assertThat(new InternalServiceJwtProperties(
                true,
                "service-2026-08",
                privateKeyPath.toString(),
                30
        ).toString()).contains("privateKeyPath=<redacted>").doesNotContain(privateKeyPath.toString());
    }

    @Test
    void enabledConfigurationRequiresDedicatedKeyReferenceAndBoundedTtl() {
        assertThatThrownBy(() -> new InternalServiceJwtProperties(true, "", "", 30))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("keyId");
        assertThatThrownBy(() -> new InternalServiceJwtProperties(false, "", "", 61))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("between 1 and 60");
    }

    @Test
    void rejectsRsaKeysBelowTheMinimumStrength() throws Exception {
        KeyPair keyPair = rsaKeyPair(1024);
        Path privateKeyPath = writePkcs8Pem((RSAPrivateKey) keyPair.getPrivate());
        var properties = new InternalServiceJwtProperties(
                true,
                "service-test",
                privateKeyPath.toString(),
                30
        );

        assertThatThrownBy(() -> InternalServiceJwtIssuer.from(properties))
                .isInstanceOf(IllegalStateException.class)
                .hasMessage("internal service JWT private key is unavailable or invalid")
                .hasNoCause();
    }

    @Test
    void disabledConfigurationDoesNotCreateAServiceJwtIssuer() {
        new ApplicationContextRunner()
                .withUserConfiguration(InternalServiceJwtConfiguration.class)
                .run(context -> assertThat(context)
                        .hasNotFailed()
                        .doesNotHaveBean(InternalServiceJwtIssuer.class));
    }

    @Test
    void enabledConfigurationWithoutDedicatedKeyReferenceFailsClosed() {
        new ApplicationContextRunner()
                .withUserConfiguration(InternalServiceJwtConfiguration.class)
                .withPropertyValues("dianlian.internal-service-jwt.enabled=true")
                .run(context -> assertThat(context)
                        .hasFailed()
                        .getFailure()
                        .hasMessageContaining("InternalServiceJwtProperties"));
    }

    private Path writePkcs8Pem(RSAPrivateKey privateKey) throws Exception {
        String encoded = Base64.getMimeEncoder(64, new byte[]{'\n'}).encodeToString(privateKey.getEncoded());
        String pem = "-----BEGIN PRIVATE KEY-----\n" + encoded + "\n-----END PRIVATE KEY-----\n";
        Path target = temporaryDirectory.resolve("temporary-test-private-key.pem");
        Files.writeString(target, pem, StandardCharsets.US_ASCII);
        return target;
    }

    private static KeyPair rsaKeyPair(int size) throws Exception {
        var generator = KeyPairGenerator.getInstance("RSA");
        generator.initialize(size);
        return generator.generateKeyPair();
    }
}
