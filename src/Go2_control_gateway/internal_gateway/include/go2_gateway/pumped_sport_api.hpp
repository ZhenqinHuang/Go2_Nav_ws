#pragma once

#include "go2_gateway/sport_api.hpp"

#include <chrono>
#include <memory>

namespace go2_gateway {

std::unique_ptr<SportApi> make_pumped_sport_api(
    std::unique_ptr<SportApi> backend,
    std::chrono::milliseconds move_period =
        std::chrono::milliseconds(100));

}  // namespace go2_gateway
