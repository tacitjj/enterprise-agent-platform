package com.dianlian.platform.model.api;

import com.dianlian.platform.identity.api.PlatformAccessContext;
import java.util.List;

public interface ModelCatalogQuery {
    List<ModelDefinitionView> list(PlatformAccessContext accessContext);

    List<PlatformDefaultModelRouteView> listPlatformDefaults(PlatformAccessContext accessContext);
}
