package com.dianlian.platform.model.infrastructure;

import com.dianlian.platform.model.api.ModelChatMessage;
import com.dianlian.platform.model.api.ModelChatRequest;
import com.dianlian.platform.model.api.ModelChatResponse;
import com.dianlian.platform.model.api.ModelGateway;
import com.dianlian.platform.model.api.ModelProviderUnavailableException;
import com.dianlian.platform.model.api.ResolvedModelRoute;
import com.dianlian.platform.model.application.ModelEndpointPolicy;
import dev.langchain4j.data.message.AiMessage;
import dev.langchain4j.data.message.ChatMessage;
import dev.langchain4j.data.message.SystemMessage;
import dev.langchain4j.data.message.UserMessage;
import dev.langchain4j.model.chat.request.ChatRequest;
import dev.langchain4j.model.openai.OpenAiChatModel;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Objects;
import org.springframework.stereotype.Component;

@Component
public class LangChain4jModelGateway implements ModelGateway {

    private final EnvironmentCredentialResolver credentialResolver;
    private final ModelEndpointPolicy endpointPolicy;

    public LangChain4jModelGateway(
            EnvironmentCredentialResolver credentialResolver,
            ModelEndpointPolicy endpointPolicy
    ) {
        this.credentialResolver = Objects.requireNonNull(
                credentialResolver,
                "credentialResolver must not be null"
        );
        this.endpointPolicy = Objects.requireNonNull(endpointPolicy, "endpointPolicy must not be null");
    }

    @Override
    public ModelChatResponse chat(ResolvedModelRoute route, ModelChatRequest request) {
        Objects.requireNonNull(route, "route must not be null");
        Objects.requireNonNull(request, "request must not be null");
        var definition = route.model();
        if (!"OPENAI_COMPATIBLE".equals(definition.protocol())) {
            throw new ModelProviderUnavailableException(
                    "MODEL_PROTOCOL_UNSUPPORTED",
                    "The configured model protocol is not supported",
                    null
            );
        }

        try {
            endpointPolicy.validate(definition.baseUrl());
            var model = OpenAiChatModel.builder()
                    .baseUrl(definition.baseUrl())
                    .apiKey(credentialResolver.resolve(definition.credentialRef()))
                    .modelName(definition.providerModelName())
                    .temperature(definition.temperature().doubleValue())
                    .maxTokens(definition.maxOutputTokens())
                    .timeout(Duration.ofSeconds(90))
                    .maxRetries(0)
                    .logRequests(false)
                    .logResponses(false)
                    .build();
            var messages = new ArrayList<ChatMessage>();
            messages.add(SystemMessage.from(request.systemInstruction()));
            for (ModelChatMessage message : request.messages()) {
                messages.add(message.role() == ModelChatMessage.Role.HUMAN
                        ? UserMessage.from(message.text())
                        : AiMessage.from(message.text()));
            }
            var response = model.chat(ChatRequest.builder().messages(messages).build());
            var usage = response.tokenUsage();
            boolean usageConfirmed = usage != null
                    && usage.inputTokenCount() != null
                    && usage.outputTokenCount() != null;
            return new ModelChatResponse(
                    response.aiMessage().text(),
                    usageConfirmed ? usage.inputTokenCount() : 0,
                    usageConfirmed ? usage.outputTokenCount() : 0,
                    usageConfirmed,
                    response.metadata() == null ? null : response.metadata().id(),
                    response.metadata() == null || response.metadata().finishReason() == null
                            ? "UNKNOWN"
                            : response.metadata().finishReason().name()
            );
        } catch (ModelProviderUnavailableException exception) {
            throw exception;
        } catch (RuntimeException exception) {
            throw new ModelProviderUnavailableException(
                    "MODEL_PROVIDER_CALL_FAILED",
                    "The model provider call failed",
                    exception
            );
        }
    }
}
