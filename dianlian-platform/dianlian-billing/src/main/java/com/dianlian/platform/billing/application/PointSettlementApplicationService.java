package com.dianlian.platform.billing.application;

import com.dianlian.platform.billing.api.PointSettlementResult;
import com.dianlian.platform.billing.api.PointSettlementService;
import com.dianlian.platform.billing.api.SettlePointsCommand;
import java.time.Clock;
import java.util.Objects;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class PointSettlementApplicationService implements PointSettlementService {

    private final PointReservationRepository repository;
    private final Clock clock;

    @Autowired
    public PointSettlementApplicationService(PointReservationRepository repository) {
        this(repository, Clock.systemUTC());
    }

    PointSettlementApplicationService(PointReservationRepository repository, Clock clock) {
        this.repository = Objects.requireNonNull(repository, "repository must not be null");
        this.clock = Objects.requireNonNull(clock, "clock must not be null");
    }

    @Override
    @Transactional
    public PointSettlementResult settle(SettlePointsCommand command) {
        return repository.settle(new SettlePointsRequest(command, clock.instant()));
    }
}
