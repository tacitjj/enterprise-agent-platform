package com.dianlian.platform.bootstrap.infrastructure.web;

import java.util.Arrays;

final class HttpEtagSupport {

    private HttpEtagSupport() {
    }

    static boolean matches(String ifNoneMatch, String currentEtag) {
        if (ifNoneMatch == null || ifNoneMatch.isBlank()) {
            return false;
        }
        var normalizedCurrent = stripWeakPrefix(currentEtag);
        return Arrays.stream(ifNoneMatch.split(","))
                .map(String::trim)
                .anyMatch(candidate -> candidate.equals("*")
                        || stripWeakPrefix(candidate).equals(normalizedCurrent));
    }

    private static String stripWeakPrefix(String etag) {
        return etag.startsWith("W/") ? etag.substring(2) : etag;
    }
}
