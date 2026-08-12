package com.dianlian.platform.billing.application;

import com.dianlian.platform.billing.api.PointReservationResult;
import com.dianlian.platform.billing.api.PointSettlementResult;

public interface PointReservationRepository {

    PointReservationResult reserve(ReservePointsRequest request);

    PointSettlementResult settle(SettlePointsRequest request);
}
