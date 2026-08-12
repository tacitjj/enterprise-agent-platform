package com.dianlian.platform.billing.api;

public interface PointSettlementService {
    PointSettlementResult settle(SettlePointsCommand command);
}
