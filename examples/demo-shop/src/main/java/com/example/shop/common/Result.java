package com.example.shop.common;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

/**
 * 统一返回结果
 */
@Data
@ApiModel("统一返回结果")
public class Result<T> {
    @ApiModelProperty(value = "状态码，0 表示成功", example = "0")
    private Integer code;
    @ApiModelProperty("提示信息")
    private String msg;
    @ApiModelProperty("业务数据")
    private T data;

    public static <T> Result<T> ok(T data) {
        Result<T> r = new Result<>();
        r.code = 0;
        r.data = data;
        return r;
    }
}
