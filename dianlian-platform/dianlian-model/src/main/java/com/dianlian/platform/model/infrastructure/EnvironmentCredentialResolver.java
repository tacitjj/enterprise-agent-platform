package com.dianlian.platform.model.infrastructure;

import com.dianlian.platform.model.api.ModelProviderUnavailableException;
import java.util.regex.Pattern;
import org.springframework.stereotype.Component;

@Component
class EnvironmentCredentialResolver {

    private static final Pattern CREDENTIAL_REF = Pattern.compile(
            "^env:DIANLIAN_MODEL_[A-Z0-9_]{1,113}$"
    );

    String resolve(String credentialRef) {
        if (credentialRef == null || !CREDENTIAL_REF.matcher(credentialRef).matches()) {
            throw new ModelProviderUnavailableException(
                    "MODEL_CREDENTIAL_REFERENCE_REJECTED",
                    "The configured model credential reference is not allowed",
                    null
            );
        }
        var variableName = credentialRef.substring("env:".length());
        var value = System.getenv(variableName);
        if (value == null || value.isBlank()) {
            throw new ModelProviderUnavailableException(
                    "MODEL_CREDENTIAL_UNAVAILABLE",
                    "The configured model credential is unavailable",
                    null
            );
        }
        return value.trim();
    }
}
