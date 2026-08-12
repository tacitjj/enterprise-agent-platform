package com.dianlian.platform.memory.api;

import com.dianlian.platform.identity.api.AccessContext;
import java.util.List;

public interface MemoryQuery {

    List<ConfirmedMemory> recallConfirmed(
            RecallConfirmedMemoryQuery query,
            AccessContext accessContext
    );
}
