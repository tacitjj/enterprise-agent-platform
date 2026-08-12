package com.dianlian.platform.billing.api;

import com.dianlian.platform.identity.api.AccessContext;

public interface PointReservationService {

    PointReservationResult reserve(ReservePointsCommand command, AccessContext accessContext);
}
