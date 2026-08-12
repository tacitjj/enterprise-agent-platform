package com.dianlian.platform.model.api;

public interface ModelGateway {
    ModelChatResponse chat(ResolvedModelRoute route, ModelChatRequest request);
}
