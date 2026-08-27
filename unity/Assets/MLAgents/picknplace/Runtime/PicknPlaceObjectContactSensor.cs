using System.Collections.Generic;
using UnityEngine;

namespace KDT.PicknPlaceTraining
{
    /// <summary>
    /// Tracks contact between one grasp contact point (fingertip 0..4, or the palm
    /// at index <see cref="Dg5fPicknPlaceSpec.PalmContactIndex"/>) and a single
    /// target collider (the grasped cube).
    ///
    /// Unlike GraspLift's GraspLiftObjectContactSensor (which matches any collider
    /// under the target Rigidbody), this checks a specific <see cref="targetCollider"/>
    /// directly — functionally equivalent for a plain single-collider cube.
    /// </summary>
    public sealed class PicknPlaceObjectContactSensor : MonoBehaviour
    {
        [Range(0, Dg5fPicknPlaceSpec.ContactPointCount - 1)]
        public int contactIndex;
        public Collider targetCollider;

        readonly HashSet<Collider> _contacts = new HashSet<Collider>();

        public bool IsTouching => _contacts.Count > 0;

        public float LastImpulse { get; private set; }

        public void ResetContacts()
        {
            _contacts.Clear();
            LastImpulse = 0f;
        }

        bool IsTarget(Collider other)
        {
            if (targetCollider == null || other == null) return false;
            return other == targetCollider || other.transform.IsChildOf(targetCollider.transform);
        }

        void Register(Collision collision)
        {
            if (collision == null || !IsTarget(collision.collider)) return;
            _contacts.Add(collision.collider);
            LastImpulse = collision.impulse.magnitude;
        }

        void OnCollisionEnter(Collision collision)
        {
            Register(collision);
        }

        void OnCollisionStay(Collision collision)
        {
            Register(collision);
        }

        void OnCollisionExit(Collision collision)
        {
            if (collision != null && collision.collider != null)
                _contacts.Remove(collision.collider);
            if (_contacts.Count == 0) LastImpulse = 0f;
        }

        void OnDisable()
        {
            ResetContacts();
        }
    }
}
