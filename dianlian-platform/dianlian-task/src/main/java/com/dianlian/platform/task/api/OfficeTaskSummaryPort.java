package com.dianlian.platform.task.api;

import com.dianlian.platform.identity.api.AccessContext;
import java.util.List;

public interface OfficeTaskSummaryPort {

    List<OfficeTaskSummary> listVisibleTasks(AccessContext accessContext, int limit);
}
