package com.example.shop.dto;

import io.swagger.annotations.ApiModelProperty;
import javax.validation.constraints.*;
import lombok.Data;

@Data
public class UserCreateDTO {
    @ApiModelProperty(value = "用户名", required = true, example = "zhangsan")
    @NotBlank(message = "用户名不能为空")
    @Size(min = 4, max = 32)
    private String username;

    @ApiModelProperty(value = "密码", required = true)
    @NotBlank
    @Size(min = 8, max = 64)
    private String password;

    @ApiModelProperty("手机号")
    @Pattern(regexp = "^1\\d{10}$", message = "手机号格式不正确")
    private String mobile;
}
