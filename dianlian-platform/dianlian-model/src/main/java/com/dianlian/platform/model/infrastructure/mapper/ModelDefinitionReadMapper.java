package com.dianlian.platform.model.infrastructure.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import java.util.List;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Result;
import org.apache.ibatis.annotations.Results;
import org.apache.ibatis.annotations.Select;

@Mapper
public interface ModelDefinitionReadMapper extends BaseMapper<ModelDefinitionReadRow> {

    @Select("""
            SELECT model_definition_id, model_code, configuration_version, display_name,
                   provider_code, protocol, base_url, provider_model_name, credential_ref,
                   capability_type, temperature, max_output_tokens,
                   input_rate_micro_credit_per_million_tokens,
                   output_rate_micro_credit_per_million_tokens,
                   reservation_ceiling_micro_credit, status, created_by, created_at
              FROM dianlian_business.model_definition
             ORDER BY model_code, configuration_version DESC
             LIMIT #{limit}
            """)
    @Results(id = "modelDefinitionReadRow", value = {
            @Result(column = "model_definition_id", property = "modelDefinitionId", id = true),
            @Result(column = "model_code", property = "modelCode"),
            @Result(column = "configuration_version", property = "configurationVersion"),
            @Result(column = "display_name", property = "displayName"),
            @Result(column = "provider_code", property = "providerCode"),
            @Result(column = "protocol", property = "protocol"),
            @Result(column = "base_url", property = "baseUrl"),
            @Result(column = "provider_model_name", property = "providerModelName"),
            @Result(column = "credential_ref", property = "credentialRef"),
            @Result(column = "capability_type", property = "capabilityType"),
            @Result(column = "temperature", property = "temperature"),
            @Result(column = "max_output_tokens", property = "maxOutputTokens"),
            @Result(column = "input_rate_micro_credit_per_million_tokens",
                    property = "inputRateMicroCreditPerMillionTokens"),
            @Result(column = "output_rate_micro_credit_per_million_tokens",
                    property = "outputRateMicroCreditPerMillionTokens"),
            @Result(column = "reservation_ceiling_micro_credit",
                    property = "reservationCeilingMicroCredit"),
            @Result(column = "status", property = "status"),
            @Result(column = "created_by", property = "createdBy"),
            @Result(column = "created_at", property = "createdAt")
    })
    List<ModelDefinitionReadRow> selectLatest(@Param("limit") int limit);
}
