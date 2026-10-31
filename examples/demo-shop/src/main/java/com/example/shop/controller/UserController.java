package com.example.shop.controller;

import com.example.shop.common.PageResult;
import com.example.shop.common.Result;
import com.example.shop.dto.UserCreateDTO;
import com.example.shop.dto.UserQuery;
import com.example.shop.vo.UserVO;
import io.swagger.annotations.Api;
import io.swagger.annotations.ApiOperation;
import io.swagger.annotations.ApiParam;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

import javax.servlet.http.HttpServletRequest;

@Api(tags = "用户管理")
@RestController
@RequestMapping("/api/v1/users")
public class UserController {

    @ApiOperation(value = "新增用户", notes = "用户名全局唯一，重复返回 1001")
    @PostMapping
    public Result<Long> create(@RequestBody @Validated UserCreateDTO dto) {
        return Result.ok(1L);
    }

    @ApiOperation("分页查询用户")
    @GetMapping("/page")
    public Result<PageResult<UserVO>> page(UserQuery query) {
        return Result.ok(null);
    }

    @ApiOperation("用户详情")
    @GetMapping("/{id}")
    public Result<UserVO> detail(@ApiParam("用户ID") @PathVariable("id") Long id) {
        return Result.ok(null);
    }

    @ApiOperation("启用/禁用用户")
    @PutMapping("/{id}/status")
    public Result<Void> changeStatus(@PathVariable Long id,
                                     @RequestParam(value = "status") Integer status,
                                     HttpServletRequest request) {
        return Result.ok(null);
    }

    @ApiOperation("批量导入用户(Excel)")
    @PostMapping(value = "/import", consumes = "multipart/form-data")
    public Result<Integer> importUsers(@RequestPart("file") MultipartFile file) {
        return Result.ok(0);
    }

    @Deprecated
    @RequestMapping(value = {"/remove/{id}", "/delete/{id}"}, method = {RequestMethod.DELETE, RequestMethod.POST})
    public Result<Void> delete(@PathVariable Long id) {
        return Result.ok(null);
    }
}
