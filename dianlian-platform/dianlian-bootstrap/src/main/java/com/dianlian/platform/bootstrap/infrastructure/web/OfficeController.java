package com.dianlian.platform.bootstrap.infrastructure.web;

import com.dianlian.platform.bootstrap.application.OfficeSnapshotApplicationService;
import com.dianlian.platform.bootstrap.application.OfficeSnapshotApplicationService.OfficeSnapshotView;
import java.util.Objects;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/office")
public final class OfficeController {

    private static final String CACHE_CONTROL = "private, no-cache, must-revalidate";

    private final OfficeSnapshotApplicationService officeService;

    public OfficeController(OfficeSnapshotApplicationService officeService) {
        this.officeService = Objects.requireNonNull(officeService, "officeService must not be null");
    }

    @GetMapping
    public ResponseEntity<OfficeSnapshotView> currentOffice(
            @RequestHeader(name = HttpHeaders.IF_NONE_MATCH, required = false) String ifNoneMatch
    ) {
        var snapshot = officeService.currentSnapshot();
        var etag = snapshot.etag();
        if (HttpEtagSupport.matches(ifNoneMatch, etag)) {
            return ResponseEntity.status(304)
                    .header(HttpHeaders.ETAG, etag)
                    .header(HttpHeaders.CACHE_CONTROL, CACHE_CONTROL)
                    .build();
        }
        return ResponseEntity.ok()
                .header(HttpHeaders.ETAG, etag)
                .header(HttpHeaders.CACHE_CONTROL, CACHE_CONTROL)
                .body(snapshot);
    }

}
