package com.example.shop.controller;

import org.springframework.web.bind.annotation.*;
import java.util.Map;

/**
 * 支付回调
 * <p>由第三方支付平台调用，不对前端开放。
 */
@RestController
@RequestMapping("/callback")
public class PayCallbackController {

    /**
     * 微信支付结果通知
     *
     * @param body 微信回调报文(XML 转 Map)
     * @return SUCCESS 表示已处理
     */
    @PostMapping("/wxpay")
    public String wxpay(@RequestBody Map<String, Object> body) {
        return "SUCCESS";
    }

    @GetMapping("/ping")
    public String ping() {
        return "pong";
    }
}
