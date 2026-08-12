package com.dianlian.platform.billing.application;

import com.dianlian.platform.billing.api.PointReservationResult;
import com.dianlian.platform.billing.api.PointReservationService;
import com.dianlian.platform.billing.api.ReservePointsCommand;
import com.dianlian.platform.identity.api.AccessContext;
import java.time.Clock;
import java.util.Objects;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

@Service
public class PointReservationApplicationService implements PointReservationService {

    private final PointReservationRepository repository;
    private final Clock clock;

    @Autowired
    public PointReservationApplicationService(PointReservationRepository repository) {
        this(repository, Clock.systemUTC());
    }

    PointReservationApplicationService(PointReservationRepository repository, Clock clock) {
        this.repository = Objects.requireNonNull(repository, "repository must not be null");
        this.clock = Objects.requireNonNull(clock, "clock must not be null");
    }

    @Override
    @Transactional(propagation = Propagation.MANDATORY)
    public PointReservationResult reserve(ReservePointsCommand command, AccessContext accessContext) {
        Objects.requireNonNull(command, "command must not be null");
        Objects.requireNonNull(accessContext, "accessContext must not be null");
        return repository.reserve(new ReservePointsRequest(
                accessContext.tenantId().value(),
                accessContext.actorId().value(),
                command,
                clock.instant()
        ));
    }
}
