package com.dianlian.platform.integration.infrastructure.context;

import com.dianlian.platform.context.api.ContextIndexDispatch.ClaimedProjection;
import com.dianlian.platform.context.api.ContextIndexDispatch.RemoteReceipt;

interface ContextIndexingRuntimeClient {

    RemoteReceipt apply(ClaimedProjection projection);
}
