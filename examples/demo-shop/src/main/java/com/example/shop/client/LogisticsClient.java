package com.example.shop.client;

import org.springframework.cloud.openfeign.FeignClient;
import org.springframework.web.bind.annotation.*;

@FeignClient(name = "logistics", url = "${logistics.base-url}")
public interface LogisticsClient {
    /** 查询物流轨迹 */
    @GetMapping("/track/{waybillNo}")
    String track(@PathVariable("waybillNo") String waybillNo);
}
