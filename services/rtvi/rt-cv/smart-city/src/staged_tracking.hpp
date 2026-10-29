// SPDX-License-Identifier: Apache-2.0
#pragma once
#include "gstnvdsmeta.h"
#include "nvds_analytics_meta.h"
#include "nvds_tracker_meta.h"
#include "tracker_3d.hpp"
#include <atomic>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>

namespace city {
// The two handles have different authorities. The first NvDCF handle is local
// analytics identity. The second MV3DT handle is an optional map association.
// This metadata travels with this exact detector object, never an IoU alias.
constexpr size_t kStagedObjectLimit=4096;
constexpr const char* kLocalTrackingMethod="nvidia-nvdcf-first-stage-9.2";
struct StagedFrameKey {
  uint64_t token=0,pts=0,ntp=0;
  int64_t source_frame=0;
  unsigned source=0,pad=0;
};
struct StagedDetection {
  StagedFrameKey key;
  NvOSD_RectParams raw_rect{};
  NvDsComp_BboxInfo raw_detector_box{};
  gint raw_class=0,raw_component=0;
  gint tracking_class=0;
  bool class_restored=false;
  float raw_confidence=0;
  uint64_t ordinal=0,local_id=UNTRACKED_OBJECT_ID;
};
struct StagedLocalObject {
  uint64_t local_id=UNTRACKED_OBJECT_ID,ordinal=0;
  gint class_id=0;
  NvOSD_RectParams rect{};
  float confidence=-1,tracker_confidence=-1;
  bool observed=false,has_analytics=false;
  std::vector<std::string> roi_status,line_crossings;
  std::string direction;
};
struct StagedFrame {
  StagedFrameKey key;
  std::vector<StagedLocalObject> local;
  // Optional diagnostic snapshot, captured before the SDK can remove tentative
  // or unmatched detections. Never supplies tracking or analytics objects.
  std::vector<StagedDetection> detector_inputs;
  size_t detector_input_count=0;
  bool detector_inputs_retained=false;
  bool prepared=false;
  uint64_t duplicate_local_ids=0,omitted_local_objects=0;
};
inline NvDsMetaType staged_frame_type() {
  static auto type=nvds_get_user_meta_type(const_cast<gchar*>("VSS.CITY.STAGED_FRAME.V1"));return type;
}
inline NvDsMetaType staged_detection_type() {
  static auto type=nvds_get_user_meta_type(const_cast<gchar*>("VSS.CITY.STAGED_DETECTION.V1"));return type;
}
template<class T> gpointer copy_staged(gpointer data,gpointer) {
  const auto* user=static_cast<NvDsUserMeta*>(data);
  return new T(*static_cast<const T*>(user->user_meta_data));
}
template<class T> void release_staged(gpointer data,gpointer) {
  auto* user=static_cast<NvDsUserMeta*>(data);
  delete static_cast<T*>(user->user_meta_data);user->user_meta_data=nullptr;
}
template<class T> NvDsUserMeta* make_staged_meta(NvDsBatchMeta* batch,NvDsMetaType type,T value) {
  auto* user=nvds_acquire_user_meta_from_pool(batch);if(!user)return nullptr;
  user->user_meta_data=new T(std::move(value));user->base_meta.meta_type=type;
  user->base_meta.copy_func=copy_staged<T>;user->base_meta.release_func=release_staged<T>;return user;
}
template<class T> T* staged_payload(NvDsUserMetaList* list,NvDsMetaType type) {
  T* found=nullptr;
  for(auto* item=list;item;item=item->next) {
    auto* user=static_cast<NvDsUserMeta*>(item->data);
    if(user->base_meta.meta_type!=type)continue;
    // Duplicate provenance is ambiguous; fail closed rather than pick one.
    if(found||!user->user_meta_data)return nullptr;
    found=static_cast<T*>(user->user_meta_data);
  }
  return found;
}
inline StagedFrame* staged_frame(NvDsFrameMeta* frame) {
  return staged_payload<StagedFrame>(frame->frame_user_meta_list,staged_frame_type());
}
inline StagedDetection* staged_detection(NvDsObjectMeta* object) {
  return staged_payload<StagedDetection>(object->obj_user_meta_list,staged_detection_type());
}
inline bool staged_key_current(const StagedFrameKey& key,const NvDsFrameMeta* frame) {
  // MV3DT deliberately replaces frame_num with an internal batch counter.
  // Original frame identity belongs to our preserved frame stamp instead.
  return key.token&&key.source==frame->source_id&&key.pad==frame->pad_index&&
      key.pts==frame->buf_pts&&key.ntp==frame->ntp_timestamp;
}
inline bool staged_detection_current(const StagedDetection* detection,const StagedFrame* current,
    const NvDsFrameMeta* frame,const NvDsObjectMeta* object) {
  return detection&&current&&staged_key_current(current->key,frame)&&
      detection->key.token==current->key.token&&staged_key_current(detection->key,frame)&&
      (detection->class_restored?detection->raw_class:detection->tracking_class)==object->class_id&&
      detection->raw_component==object->unique_component_id;
}
inline bool stamp_staged_detections(NvDsBatchMeta* batch,NvDsFrameMeta* frame,uint64_t token,
    bool retain_detector_inputs=false,bool car_truck_family=false) {
  if(!token||staged_frame(frame))return false;
  StagedFrame stamp;stamp.key.token=token;stamp.key.source_frame=frame->frame_num;
  stamp.key.pts=frame->buf_pts;stamp.key.ntp=frame->ntp_timestamp;
  stamp.key.source=frame->source_id;stamp.key.pad=frame->pad_index;
  stamp.detector_inputs_retained=retain_detector_inputs;
  auto* user=make_staged_meta(batch,staged_frame_type(),std::move(stamp));if(!user)return false;
  nvds_add_user_meta_to_frame(frame,user);
  auto* current=static_cast<StagedFrame*>(user->user_meta_data);
  size_t count=0;
  for(auto* item=frame->obj_meta_list;item;item=item->next) {
    auto* object=static_cast<NvDsObjectMeta*>(item->data);
    if(!frame->bInferDone||object->class_id<0||object->class_id>=7||!std::isfinite(object->confidence)||object->confidence<0)continue;
    if(++count>kStagedObjectLimit||staged_detection(object))return false;
    StagedDetection detection;detection.key=current->key;detection.raw_rect=object->rect_params;
    detection.raw_detector_box=object->detector_bbox_info;detection.raw_class=object->class_id;
    // Canonicalize only this detector object's SDK input. Class matching stays
    // enabled inside MV3DT, so people/buses/bikes cannot match this family.
    // Keep the raw classification on the exact-object stamp for restoration.
    detection.tracking_class=car_truck_family&&object->class_id==5?2:object->class_id;
    detection.raw_component=object->unique_component_id;detection.raw_confidence=object->confidence;
    detection.ordinal=count;
    auto* meta=make_staged_meta(batch,staged_detection_type(),detection);if(!meta)return false;
    nvds_add_user_meta_to_obj(object,meta);
    current->detector_input_count=count;
    if(retain_detector_inputs)current->detector_inputs.push_back(detection);
    object->class_id=detection.tracking_class;
  }
  return true;
}
inline bool restore_native_detector_classes(NvDsFrameMeta* frame) {
  auto* current=staged_frame(frame);
  if(!current||!staged_key_current(current->key,frame))return false;
  for(auto* item=frame->obj_meta_list;item;item=item->next) {
    auto* object=static_cast<NvDsObjectMeta*>(item->data);
    auto* detection=staged_detection(object);
    // SDK-created predictions/peers have no current detector authority.
    if(!staged_detection_current(detection,current,frame,object))continue;
    object->class_id=detection->raw_class;detection->class_restored=true;
  }
  return true;
}
inline bool first_tracker_batch_meta(NvDsMetaType type) {
  return type==NVDS_TRACKER_PAST_FRAME_META||type==NVDS_TRACKER_BATCH_REID_META||
      type==NVDS_TRACKER_TERMINATED_LIST_META||type==NVDS_TRACKER_SHADOW_LIST_META;
}
inline void remove_first_tracker_batch_meta(NvDsBatchMeta* batch) {
  for(auto* item=batch->batch_user_meta_list;item;) {
    auto* next=item->next;auto* meta=static_cast<NvDsUserMeta*>(item->data);
    if(first_tracker_batch_meta(meta->base_meta.meta_type))nvds_remove_user_meta_from_batch(batch,meta);
    item=next;
  }
}
inline bool first_tracker_projection_meta(NvDsMetaType type) {
  return type==NVDS_OBJ_VISIBILITY||type==NVDS_OBJ_IMAGE_FOOT_LOCATION||
      type==NVDS_OBJ_WORLD_FOOT_LOCATION||type==NVDS_OBJ_IMAGE_CONVEX_HULL||type==NVDS_OBJ_3D_META;
}
inline bool prepare_staged_second_input(NvDsBatchMeta*,NvDsFrameMeta* frame) {
  auto* current=staged_frame(frame);
  if(!current||current->prepared||!staged_key_current(current->key,frame))return false;
  DemoTrackIdCounts local_ids;
  for(auto* item=frame->obj_meta_list;item;item=item->next)
    local_ids.observe(static_cast<NvDsObjectMeta*>(item->data)->object_id);
  if(local_ids.capacity_exceeded)return false;
  current->duplicate_local_ids=local_ids.duplicate_ids;
  current->omitted_local_objects=local_ids.omitted_objects();
  size_t count=0;
  for(auto* item=frame->obj_meta_list;item;) {
    auto* next=item->next;auto* object=static_cast<NvDsObjectMeta*>(item->data);
    if(++count>kStagedObjectLimit)return false;
    auto* detection=staged_detection(object);
    const bool valid_local=object->class_id>=0&&object->class_id<7&&object->object_id!=UNTRACKED_OBJECT_ID&&!local_ids.reject(object->object_id);
    const bool observed=valid_local&&staged_detection_current(detection,current,frame,object);
    if(valid_local) {
      StagedLocalObject local;local.local_id=object->object_id;local.class_id=object->class_id;
      local.rect=object->rect_params;local.observed=observed;
      local.confidence=observed?detection->raw_confidence:-1;local.tracker_confidence=object->tracker_confidence;
      local.ordinal=observed?detection->ordinal:0;
      for(auto* user_item=object->obj_user_meta_list;user_item;user_item=user_item->next) {
        auto* user=static_cast<NvDsUserMeta*>(user_item->data);
        if(user->base_meta.meta_type==NVDS_USER_OBJ_META_NVDSANALYTICS&&user->user_meta_data) {
          const auto* analytics=static_cast<NvDsAnalyticsObjInfo*>(user->user_meta_data);
          local.has_analytics=true;local.roi_status=analytics->roiStatus;
          local.line_crossings=analytics->lcStatus;local.direction=analytics->dirStatus;
        }
      }
      current->local.push_back(std::move(local));
    }
    if(!observed) {
      // Shadow predictions are available in the local snapshot as unobserved;
      // they never become fresh detector inputs for the second tracker.
      nvds_remove_obj_meta_from_frame(frame,object);item=next;continue;
    }
    detection->local_id=object->object_id;
    object->rect_params=detection->raw_rect;object->detector_bbox_info=detection->raw_detector_box;
    object->class_id=detection->raw_class;object->unique_component_id=detection->raw_component;
    object->confidence=detection->raw_confidence;object->object_id=UNTRACKED_OBJECT_ID;
    object->tracker_bbox_info={};object->tracker_confidence=-1;
    for(auto* user_item=object->obj_user_meta_list;user_item;) {
      auto* next_user=user_item->next;auto* user=static_cast<NvDsUserMeta*>(user_item->data);
      if(first_tracker_projection_meta(user->base_meta.meta_type))nvds_remove_user_meta_from_object(object,user);
      user_item=next_user;
    }
    item=next;
  }
  current->prepared=true;return true;
}
// Only a current, same-object second output can provide a map handle. New SDK
// prediction/peer objects have no stamp and can never borrow a local identity.
inline NvDsObjectMeta* staged_map_object(NvDsFrameMeta* frame,const StagedLocalObject& local,
    const DemoTrackIdCounts& global_ids) {
  auto* current=staged_frame(frame);if(!current||!current->prepared||!local.observed)return nullptr;
  NvDsObjectMeta* found=nullptr;
  for(auto* item=frame->obj_meta_list;item;item=item->next) {
    auto* object=static_cast<NvDsObjectMeta*>(item->data);const auto* detection=staged_detection(object);
    if(!staged_detection_current(detection,current,frame,object)||detection->local_id!=local.local_id||
       detection->ordinal!=local.ordinal||object->class_id!=local.class_id||
       object->object_id==UNTRACKED_OBJECT_ID||global_ids.reject(object->object_id)||
       !std::isfinite(object->confidence)||object->confidence<0)continue;
    if(found)return nullptr;
    found=object;
  }
  return found;
}
// The first config is deliberately ordinary NvDCF, with no second 3D/ReID
// authority. This bounded scalar check rejects unsupported YAML features.
inline void validate_staged_local_config(const std::string& path) {
  std::ifstream input(path);if(!input)throw std::runtime_error("Cannot read --local-tracker-config");
  std::unordered_map<std::string,std::string> values;std::string line;size_t bytes=0;
  while(std::getline(input,line)) {
    bytes+=line.size();if(bytes>262144)throw std::runtime_error("Local tracker config exceeds bound");
    line=line.substr(0,line.find('#'));const auto colon=line.find(':');if(colon==std::string::npos)continue;
    auto trim=[](std::string value){const auto begin=value.find_first_not_of(" \t\r");
      return begin==std::string::npos?std::string():value.substr(begin,value.find_last_not_of(" \t\r")-begin+1);};
    const auto key=trim(line.substr(0,colon)),value=trim(line.substr(colon+1));
    if(!value.empty())values[key]=value;
    if(line.find('&')!=std::string::npos||line.find('*')!=std::string::npos||line.find('!')!=std::string::npos)
      throw std::runtime_error("Local tracker config must use explicit scalar values");
  }
  for(const auto& required:std::vector<std::pair<std::string,std::string>>{
      {"stateEstimatorType","1"},{"visualTrackerType","2"},{"reidType","0"},{"checkClassMatch","1"}})
    if(values[required.first]!=required.second)throw std::runtime_error("Local tracker must be ordinary class-matched 2D NvDCF without ReID");
  for(const auto* key:{"enableLatePeerReAssoc","enableIDCorrection","useBatchNumForFrameId","outputReidTensor"})
    if(values.count(key)&&values[key]!="0")throw std::runtime_error("Local tracker config enables unsupported shared/projection output");
}
}
