package com.dianlian.platform.context.api;

import com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.ContextBundle;
import com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.ContextRetrievalRequest;

/**
 * Runtime boundary only. Implementations must not widen the allowlists contained in the request.
 */
public interface AuthorizedContextRetrievalPort {

    ContextBundle retrieve(ContextRetrievalRequest request);
}
