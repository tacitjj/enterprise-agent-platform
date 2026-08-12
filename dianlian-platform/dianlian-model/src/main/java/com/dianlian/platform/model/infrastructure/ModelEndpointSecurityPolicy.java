package com.dianlian.platform.model.infrastructure;

import com.dianlian.platform.model.application.ModelEndpointPolicy;
import java.net.IDN;
import java.net.Inet4Address;
import java.net.Inet6Address;
import java.net.InetAddress;
import java.net.URI;
import java.net.UnknownHostException;
import java.util.Arrays;
import java.util.Locale;
import java.util.Set;
import java.util.stream.Collectors;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

@Component
class ModelEndpointSecurityPolicy implements ModelEndpointPolicy {

    private final Set<String> allowedHosts;
    private final HostResolver hostResolver;

    @Autowired
    ModelEndpointSecurityPolicy(@Value("${dianlian.model.allowed-hosts:}") String configuredAllowedHosts) {
        this(configuredAllowedHosts, InetAddress::getAllByName);
    }

    ModelEndpointSecurityPolicy(String configuredAllowedHosts, HostResolver hostResolver) {
        this.allowedHosts = Arrays.stream(configuredAllowedHosts.split(","))
                .map(String::trim)
                .filter(value -> !value.isEmpty())
                .map(ModelEndpointSecurityPolicy::canonicalHost)
                .collect(Collectors.toUnmodifiableSet());
        this.hostResolver = hostResolver;
    }

    @Override
    public void validate(String baseUrl) {
        URI uri;
        try {
            uri = URI.create(baseUrl);
        } catch (RuntimeException exception) {
            throw rejected();
        }
        if (!"https".equalsIgnoreCase(uri.getScheme())
                || uri.isOpaque()
                || uri.getHost() == null
                || uri.getRawUserInfo() != null
                || uri.getRawQuery() != null
                || uri.getRawFragment() != null
                || (uri.getPort() != -1 && uri.getPort() != 443)) {
            throw rejected();
        }

        var host = canonicalHost(uri.getHost());
        if (isLocalHostname(host) || !allowedHosts.contains(host)) {
            throw rejected();
        }
        InetAddress[] addresses;
        try {
            addresses = hostResolver.resolve(host);
        } catch (UnknownHostException exception) {
            throw rejected();
        }
        if (addresses.length == 0 || Arrays.stream(addresses).anyMatch(ModelEndpointSecurityPolicy::isUnsafeAddress)) {
            throw rejected();
        }
    }

    private static String canonicalHost(String value) {
        var host = value.trim().toLowerCase(Locale.ROOT);
        while (host.endsWith(".")) {
            host = host.substring(0, host.length() - 1);
        }
        try {
            return IDN.toASCII(host, IDN.USE_STD3_ASCII_RULES).toLowerCase(Locale.ROOT);
        } catch (IllegalArgumentException exception) {
            throw rejected();
        }
    }

    private static boolean isLocalHostname(String host) {
        return "localhost".equals(host) || host.endsWith(".localhost") || host.endsWith(".local");
    }

    private static boolean isUnsafeAddress(InetAddress address) {
        if (address.isAnyLocalAddress()
                || address.isLoopbackAddress()
                || address.isLinkLocalAddress()
                || address.isSiteLocalAddress()
                || address.isMulticastAddress()) {
            return true;
        }
        byte[] bytes = address.getAddress();
        if (address instanceof Inet4Address) {
            return isUnsafeIpv4(bytes, 0);
        }
        if (!(address instanceof Inet6Address)) {
            return true;
        }
        if ((bytes[0] & 0xfe) == 0xfc) {
            return true;
        }
        boolean ipv4Mapped = true;
        for (int index = 0; index < 10; index++) {
            ipv4Mapped &= bytes[index] == 0;
        }
        ipv4Mapped &= bytes[10] == (byte) 0xff && bytes[11] == (byte) 0xff;
        return ipv4Mapped && isUnsafeIpv4(bytes, 12);
    }

    private static boolean isUnsafeIpv4(byte[] bytes, int offset) {
        int first = Byte.toUnsignedInt(bytes[offset]);
        int second = Byte.toUnsignedInt(bytes[offset + 1]);
        return first == 0
                || first == 10
                || first == 127
                || (first == 100 && second >= 64 && second <= 127)
                || (first == 169 && second == 254)
                || (first == 172 && second >= 16 && second <= 31)
                || (first == 192 && second == 168)
                || first >= 224;
    }

    private static IllegalArgumentException rejected() {
        return new IllegalArgumentException("model baseUrl is not an allowed public endpoint");
    }

    @FunctionalInterface
    interface HostResolver {
        InetAddress[] resolve(String host) throws UnknownHostException;
    }
}
