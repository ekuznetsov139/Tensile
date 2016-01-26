
/*******************************************************************************
 * Cobalt.h
 * - public API
 ******************************************************************************/
#ifndef COBALT_H
#define COBALT_H

#if Cobalt_BACKEND_OPENCL12
#include "CL/cl.h"
typedef cl_float2 CobaltComplexFloat;
typedef cl_double2 CobaltComplexDouble;
#else

#if (defined( __GNUC__ ) || defined( __IBMC__ ))
    #define Cobalt_ALIGNED(_x) __attribute__ ((aligned(_x)))
#else
    #define Cobalt_ALIGNED(_x)
#endif

typedef union {
   float  Cobalt_ALIGNED(8) s[2];
   struct{ float  x, y; };
   struct{ float  s0, s1; };
} CobaltComplexFloat;

typedef union {
   double  Cobalt_ALIGNED(8) s[2];
   struct{ double  x, y; };
   struct{ double  s0, s1; };
} CobaltComplexDouble;

#endif


#ifdef __cplusplus
extern "C" {
#endif

/*******************************************************************************
 * Status
 ******************************************************************************/
typedef enum CobaltStatus_ {

  // success
  cobaltStatusSuccess = 0,

  /* VALIDATION ERRORS */
  cobaltStatusValidationErrorMin,
  
  /* cobaltValidateProblem() */

  // tensor errors
  cobaltStatusTensorNumDimensionsInvalidA,
  cobaltStatusTensorNumDimensionsInvalidB,
  cobaltStatusTensorNumDimensionsInvalidC,
  cobaltStatusTensorDimensionSizeInvalidA,
  cobaltStatusTensorDimensionSizeInvalidB,
  cobaltStatusTensorDimensionSizeInvalidC,
  cobaltStatusTensorDimensionStrideInvalidA,
  cobaltStatusTensorDimensionStrideInvalidB,
  cobaltStatusTensorDimensionStrideInvalidC,
  
  // operation errors
  cobaltStatusOperandNumDimensionsMismatch,
  cobaltStatusOperationOperandNumIndicesMismatch,
  cobaltStatusOperationNumIndicesMismatch,
  cobaltStatusOperationIndexAssignmentInvalidA,
  cobaltStatusOperationIndexAssignmentInvalidB,
  cobaltStatusOperationIndexAssignmentDuplicateA,
  cobaltStatusOperationIndexAssignmentDuplicateB,
  cobaltStatusOperationNumIndicesInvalid,
  cobaltStatusOperationNumFreeIndicesInvalid,
  cobaltStatusOperationNumSummationIndicesInvalid,
  cobaltStatusOperationIndexUnassigned,
  cobaltStatusOperationFreeIndexAssignmentsInvalid,
  cobaltStatusOperationBatchIndexAssignmentsInvalid,
  cobaltStatusOperationSummationIndexAssignmentsInvalid,

  // device profile errors
  cobaltStatusDeviceProfileDeviceNameInvalid,

  /* cobaltGetSolution() */
  cobaltStatusOperationTypeNotFound,
  cobaltStatusDeviceProfileNumDevicesInvalid,
  cobaltStatusDeviceProfileNotFound,
  cobaltStatusProblemNotSupported, // purposefully not supported
  cobaltStatusProblemNotFound, // should be supported but wasn't found


  /* control errors */
  cobaltStatusControlInvalid,
  cobaltStatusDependencyInvalid,

  /* misc */
  cobaltStatusParametersInvalid,

  cobaltStatusValidationErrorMax,
  cobaltStatusPerformanceWarningMin,

  /* Performance Warnings */

  /* cobaltEnqueueSolution() */
  cobaltStatusPerformanceWarningProblemSizeTooSmall,

  cobaltStatusPerformanceWarningMax,


} CobaltStatus;

/*******************************************************************************
 * Status is Error (incorrect) vs Warning (correct but slow)
 ******************************************************************************/
bool cobaltStatusIsValidationError( CobaltStatus status );
bool cobaltStatusIsPerformanceWarning( CobaltStatus status );


/*******************************************************************************
 * Tensor
 ******************************************************************************/
typedef enum CobaltDataType_ {
  cobaltDataTypeSingle,
  cobaltDataTypeDouble,
  cobaltDataTypeSingleComplex,
  cobaltDataTypeDoubleComplex
} CobaltDataType;

typedef struct CobaltDimension_ {
  size_t stride;
  size_t size;
} CobaltDimension;

typedef struct CobaltTensor_ {
  CobaltDataType dataType;
  enum { maxDimensions = 16 } maxDimensions_;
  size_t numDimensions;
  CobaltDimension dimensions[maxDimensions];
} CobaltTensor;


/*******************************************************************************
 * Tensor Data - OpenCL 1.2
 ******************************************************************************/
#if Cobalt_BACKEND_OPENCL12
#include "CL/cl.h"

typedef struct CobaltTensorData {
  cl_mem data;
  size_t offset;
} CobaltTensorData;

/*******************************************************************************
 * Tensor Data - HCC
 ******************************************************************************/
#elif Cobalt_BACKEND_HCC
typedef void* CobaltTensorData;

/*******************************************************************************
 * Tensor Data - HSA
 ******************************************************************************/
#elif Cobalt_BACKEND_HSA  
typedef void* CobaltTensorData;

#endif

/*******************************************************************************
 * Device
 ******************************************************************************/
typedef struct CobaltDevice_ {
  enum { maxNameLength = 256 } maxNameLength_;
  char name[maxNameLength];
  size_t numComputeUnits;
  size_t clockFrequency;
} CobaltDevice;

typedef struct CobaltDeviceProfile_ {
  enum { maxDevices = 1 } maxDevices_;
  size_t numDevices;
  CobaltDevice devices[maxDevices];
} CobaltDeviceProfile;


/*******************************************************************************
 * Operation
 ******************************************************************************/
typedef enum CobaltOperationType_ {
  cobaltOperationTypeContraction,
  cobaltOperationTypeConvolution
  //cobaltOperationTypeCorrelation
} CobaltOperationType;


typedef struct CobaltOperation_ {
  // C[i,j,k] = Sum_l Sum_m Sum_n A[n,l,i,m,j] B[j,l,m,k,n]
  //   0,1,2        3     4     5   5 3 0 4 1    1 3 4 2 5
  // free indices: i, k
  // batch indices: j
  // summation indices: l m n
  // indexAssignmentsA: {5, 3, 0, 4, 1}
  // indexAssignmentsB: {1, 3, 4, 2, 5}

  CobaltOperationType type;
  CobaltDataType alphaType;
  void *alpha;
  CobaltDataType betaType;
  void *beta;
  size_t numIndicesFree;
  size_t numIndicesBatch;
  size_t numIndicesSummation;
  size_t indexAssignmentsA[CobaltTensor::maxDimensions];
  size_t indexAssignmentsB[CobaltTensor::maxDimensions];

  // used for convolutions/correlations only
  size_t pad[CobaltTensor::maxDimensions];
  size_t stride[CobaltTensor::maxDimensions];
  // size_t upscale[CobaltOperation::maxSummationIndices]; // cuDNN requires 1

} CobaltOperation;


/*******************************************************************************
 * Problem
 ******************************************************************************/
typedef struct CobaltProblem_ {
  CobaltTensor tensorC;
  CobaltTensor tensorA;
  CobaltTensor tensorB;
  CobaltDeviceProfile deviceProfile;
  CobaltOperation operation;
} CobaltProblem;

CobaltStatus cobaltValidateProblem( CobaltProblem problem );

/*******************************************************************************
 * Control
 ******************************************************************************/
typedef struct CobaltControl_ {
  size_t numDependencies;
#if Cobalt_BACKEND_OPENCL12
  enum { maxQueues = 16 } maxQueues_;
  size_t numQueues;
  cl_command_queue queues[maxQueues];
  cl_uint numInputEvents; // superfluous for AMD
  cl_event *inputEvents; // superfluous for AMD
  cl_uint numOutputEvents; // superfluous for AMD
  cl_event *outputEvents; // superfluous for AMD
#endif
} CobaltControl;


/*******************************************************************************
 * Solution
 ******************************************************************************/
struct CobaltSolution; // forward declaration

CobaltStatus cobaltGetSolution(
    const CobaltProblem problem,
    struct CobaltSolution **solution );

CobaltStatus cobaltEnqueueSolution(
    struct CobaltSolution *solution,
    CobaltTensorData tensorDataC,
    CobaltTensorData tensorDataA,
    CobaltTensorData tensorDataB,
    CobaltControl *control );


/*******************************************************************************
 * Setup & Teardown
 ******************************************************************************/
CobaltStatus cobaltSetup();
CobaltStatus cobaltTeardown();


/*******************************************************************************
 * toStrings
 ******************************************************************************/
CobaltStatus cobaltStatusToString(
    CobaltStatus code, char *cstr, size_t *size );
CobaltStatus cobaltStatusToString(
    CobaltStatus status, char *cstr, size_t *size );
CobaltStatus cobaltDataTypeToString(
    CobaltDataType dataType, char *cstr, size_t *size );
CobaltStatus cobaltOperationToString(
    CobaltOperationType type, char *cstr, size_t *size );
CobaltStatus cobaltProblemToString(
    CobaltProblem problem, char *cstr, size_t *size );


#ifdef __cplusplus
} // extern "C"
#endif

#endif // COBALT_H
