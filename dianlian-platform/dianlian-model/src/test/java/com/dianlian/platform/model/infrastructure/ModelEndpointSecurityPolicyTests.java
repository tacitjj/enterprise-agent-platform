package com.dianlian.platform.model.infrastructure;

import static org.assertj.core.api.Assertions.assertThatCode;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.net.InetAddress;
import java.net.Inet6Address;
import org.junit.jupiter.api.Test;

class ModelEndpointSecurityPolicyTests {

    @Test
    void acceptsAnExactAllowlistedPublicEndpoint() throws Exception {
        var policy = new ModelEndpointSecurityPolicy(
                "api.example.com",
                host -> new InetAddress[]{InetAddress.getByAddress(new byte[]{8, 8, 8, 8})}
        );

        assertThatCode(() -> policy.validate("https://api.example.com/v1"))
                .doesNotThrowAnyException();
    }

    @Test
    void rejectsNonAllowlistedAndUserInfoEndpoints() throws Exception {
        var policy = new ModelEndpointSecurityPolicy(
                "api.example.com",
                host -> new InetAddress[]{InetAddress.getByAddress(new byte[]{8, 8, 8, 8})}
        );

        assertThatThrownBy(() -> policy.validate("https://other.example.com/v1"))
                .isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> policy.validate("https://user@api.example.com/v1"))
                .isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void rejectsAllowlistedHostsResolvingToLoopbackOrPrivateNetworks() throws Exception {
        var loopback = new ModelEndpointSecurityPolicy(
                "api.example.com",
                host -> new InetAddress[]{InetAddress.getByAddress(new byte[]{127, 0, 0, 1})}
        );
        var privateNetwork = new ModelEndpointSecurityPolicy(
                "api.example.com",
                host -> new InetAddress[]{InetAddress.getByAddress(new byte[]{10, 0, 0, 1})}
        );

        assertThatThrownBy(() -> loopback.validate("https://api.example.com/v1"))
                .isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> privateNetwork.validate("https://api.example.com/v1"))
                .isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void rejectsIpv4MappedIpv6PrivateAddresses() throws Exception {
        byte[] mappedLoopback = new byte[16];
        mappedLoopback[10] = (byte) 0xff;
        mappedLoopback[11] = (byte) 0xff;
        mappedLoopback[12] = 127;
        mappedLoopback[15] = 1;
        var policy = new ModelEndpointSecurityPolicy(
                "api.example.com",
                host -> new InetAddress[]{Inet6Address.getByAddress(null, mappedLoopback, -1)}
        );

        assertThatThrownBy(() -> policy.validate("https://api.example.com/v1"))
                .isInstanceOf(IllegalArgumentException.class);
    }
}
