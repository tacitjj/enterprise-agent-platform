package com.dianlian.platform.memory.api;

import com.dianlian.platform.identity.api.AccessContext;

public interface MemoryCommands {

    MemoryCommandOutcome<MemoryCandidateSnapshot> propose(
            ProposeMemoryCandidateCommand command,
            AccessContext accessContext
    );

    MemoryCommandOutcome<MemoryCandidateSnapshot> confirm(
            ConfirmMemoryCandidateCommand command,
            AccessContext accessContext
    );

    MemoryCommandOutcome<MemoryCandidateSnapshot> reject(
            RejectMemoryCandidateCommand command,
            AccessContext accessContext
    );

    MemoryCommandOutcome<ConfirmedMemory> correct(
            CorrectMemoryCommand command,
            AccessContext accessContext
    );

    MemoryCommandOutcome<ConfirmedMemory> forget(
            ForgetMemoryCommand command,
            AccessContext accessContext
    );
}
